import asyncio
import json
import logging
import re
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.catalog import DISCLAIMER, DISEASES, public_catalog
from app.config import Settings
from app.db import connect, initialize
from app.middleware import BodyLimitMiddleware, mutation_origin_allowed
from app.ml import ModelStore
from app.rag import answer, retrieve
from app.reports import MAX_UPLOAD, extract_report, make_pdf
from app.security import (
    DUMMY_HASH,
    create_session,
    current_user,
    digest,
    hasher,
    limit,
    verify_password,
)

Disease = Literal["diabetes", "heart", "kidney"]
User = Annotated[dict, Depends(current_user)]
STATIC = Path(__file__).with_name("static")
logger = logging.getLogger("uvicorn.error")


class UsernameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=50)

    @field_validator("username")
    @classmethod
    def username_format(cls, value):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", value):
            raise ValueError("Use letters, numbers, underscores, dots or hyphens")
        return value.lower()


class Credentials(UsernameInput):
    password: str = Field(min_length=12, max_length=128)


class AssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disease: Disease
    features: dict[str, float] = Field(max_length=10)
    confirmed: bool

    @field_validator("features", mode="before")
    @classmethod
    def strict_numbers(cls, value):
        if not isinstance(value, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values()
        ):
            raise ValueError("Feature values must be JSON numbers")
        return value


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1500)
    disease: Disease | None = None
    external_consent: bool = False


def create_app(settings=None):
    settings = settings or Settings()
    settings.validate_deployment()

    @asynccontextmanager
    async def lifespan(app):
        initialize(settings)
        app.state.models = ModelStore(settings)
        app.state.chat_slots = asyncio.Semaphore(4)
        app.state.upload_slots = asyncio.Semaphore(2)
        if settings.production and set(app.state.models.models) != set(DISEASES):
            raise ValueError("Production requires trained models for all disease modules")
        yield

    app = FastAPI(title="HealthLens Research API", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    host = urlparse(settings.app_origin).hostname
    allowed = (
        [host] if settings.production else list({host, "localhost", "127.0.0.1", "testserver"})
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed)
    app.add_middleware(BodyLimitMiddleware)

    @app.middleware("http")
    async def safeguards(request, call_next):
        request_id = secrets.token_hex(8)
        if settings.transport_mode == "private_tunnel":
            peer = request.client.host if request.client else ""
            forwarded_host = request.headers.get(
                "x-forwarded-host", request.headers.get("host", "")
            )
            if (
                peer not in {"127.0.0.1", "::1"}
                or request.headers.get("x-forwarded-proto") != "https"
                or forwarded_host.lower() != urlparse(settings.app_origin).netloc.lower()
            ):
                return Response(
                    "Use the configured private HTTPS tunnel address. Forwarding headers are accepted only from loopback for that exact address.",
                    status_code=403,
                )
            # Only the explicitly configured loopback tunnel can assert the external HTTPS scheme.
            request.scope["scheme"] = "https"
        if request.url.scheme != "https":
            return Response("HTTPS is required", status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if (
                request.headers.get("x-requested-with") != "HealthLens"
                or not mutation_origin_allowed(request, settings)
                or request.headers.get("sec-fetch-site") == "cross-site"
            ):
                logger.warning(
                    "Mutation rejected: origin=%r expected=%r marker=%r fetch_site=%r backend_host=%r",
                    (origin or "")[:200],
                    settings.app_origin,
                    request.headers.get("x-requested-with", "")[:100],
                    request.headers.get("sec-fetch-site", "")[:100],
                    request.headers.get("host", "")[:200],
                )
                return JSONResponse(
                    {"detail": "The request was blocked by the application's origin/CSRF check."},
                    status_code=403,
                )
        if request.headers.get("content-length"):
            try:
                if int(request.headers["content-length"]) > MAX_UPLOAD + 65536:
                    return Response("Request too large", status_code=413)
            except ValueError:
                return Response("Invalid Content-Length", status_code=400)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                "Cache-Control": "no-store",
                "X-Request-ID": request_id,
            }
        )
        if settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request):
        if len(request.app.state.models.models) != len(DISEASES):
            raise HTTPException(503, "Train all three models, then restart")
        with connect(settings) as db:
            db.execute("SELECT 1")
        return {"status": "ready"}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.post("/api/auth/register", status_code=201)
    def register(body: Credentials, request: Request, response: Response):
        limit(request, "auth", 10, 300)
        user_id = uuid.uuid4().hex
        encoded = hasher.hash(body.password)
        try:
            with connect(settings) as db:
                db.execute("INSERT INTO users VALUES (?, ?, ?)", (user_id, body.username, encoded))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Username unavailable") from None
        create_session(response, request, user_id)
        return {"username": body.username}

    @app.post("/api/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        limit(request, "auth", 10, 300)
        with connect(settings) as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        valid = verify_password(row["password"] if row else DUMMY_HASH, body.password)
        if not row or not valid:
            raise HTTPException(401, "Incorrect username or password")
        create_session(response, request, row["id"])
        return {"username": row["username"]}

    @app.post("/api/auth/account-status")
    def account_status(body: UsernameInput, request: Request):
        if settings.production:
            raise HTTPException(
                404, "Account checks are unavailable in production; use sign-in or registration."
            )
        limit(request, "account_lookup", 10, 300)
        with connect(settings) as db:
            exists = bool(
                db.execute(
                    "SELECT EXISTS(SELECT 1 FROM users WHERE username=?)",
                    (body.username,),
                ).fetchone()[0]
            )
        return {"exists": exists}

    @app.get("/api/auth/me")
    def me(user: User):
        return {"username": user["username"]}

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response):
        with connect(settings) as db:
            db.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (digest(request.cookies.get("healthlens_session", "")),),
            )
        response.delete_cookie(
            "healthlens_session",
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )

    @app.delete("/api/account", status_code=204)
    def delete_account(body: Credentials, request: Request, response: Response, user: User):
        limit(request, "reauth", 5, 300)
        with connect(settings) as db:
            row = db.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()
            if body.username != user["username"] or not verify_password(
                row["password"], body.password
            ):
                raise HTTPException(401, "Incorrect credentials")
            db.execute("DELETE FROM users WHERE id=?", (user["id"],))
        response.delete_cookie(
            "healthlens_session",
            path="/",
            secure=True,
            httponly=True,
            samesite="strict",
        )

    @app.get("/api/catalog")
    def catalog(request: Request, user: User):
        return {
            "diseases": public_catalog(),
            "disclaimer": DISCLAIMER,
            "external_chat_available": bool(settings.external_chat_provider),
            "external_chat_provider": settings.external_chat_provider,
            "external_chat_models": settings.nvidia_model_candidates
            if settings.external_chat_provider == "nvidia"
            else [],
            "models": request.app.state.models.metadata,
        }

    @app.post("/api/uploads/extract")
    async def upload(
        request: Request,
        user: User,
        disease: Disease,
        file: Annotated[UploadFile, File()],
    ):
        limit(request, "upload", 10, 60)
        try:
            data = await file.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "Maximum upload size is 2 MB")
            async with request.app.state.upload_slots:
                try:
                    return await run_in_threadpool(extract_report, file.filename, data, disease)
                except (ValueError, KeyError) as exc:
                    raise HTTPException(422, str(exc)) from None
        finally:
            await file.close()

    @app.post("/api/assessments", status_code=201)
    def assess(body: AssessmentInput, request: Request, user: User):
        limit(request, "assessment", 20, 60)
        if body.confirmed is not True:
            raise HTTPException(422, "Confirm inputs and educational-use notice")
        try:
            result = request.app.state.models.predict(body.disease, body.features)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except LookupError as exc:
            raise HTTPException(503, str(exc)) from None
        sources, _ = retrieve("healthy eating physical activity clinician follow up", body.disease)
        item = {
            "id": uuid.uuid4().hex,
            "created": datetime.now(timezone.utc).isoformat(),
            "result": result,
            "guidance": sources,
            "disclaimer": DISCLAIMER,
        }
        with connect(settings) as db:
            count = db.execute(
                "SELECT count(*) FROM assessments WHERE user_id=?", (user["id"],)
            ).fetchone()[0]
            if count >= 200:
                raise HTTPException(409, "History limit reached; delete old assessments")
            db.execute(
                "INSERT INTO assessments VALUES (?, ?, ?, ?)",
                (item["id"], user["id"], item["created"], json.dumps(item, allow_nan=False)),
            )
        return item

    def owned_assessment(item_id, user):
        with connect(settings) as db:
            row = db.execute(
                "SELECT payload FROM assessments WHERE id=? AND user_id=?", (item_id, user["id"])
            ).fetchone()
        if not row:
            raise HTTPException(404, "Assessment not found")
        return json.loads(row["payload"])

    @app.get("/api/assessments")
    def history(user: User, offset: int = 0):
        if offset < 0:
            raise HTTPException(422, "Offset must not be negative")
        with connect(settings) as db:
            rows = db.execute(
                "SELECT payload FROM assessments WHERE user_id=? ORDER BY created DESC LIMIT 20 OFFSET ?",
                (user["id"], offset),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    @app.get("/api/assessments/{item_id}")
    def detail(item_id: str, user: User):
        return owned_assessment(item_id, user)

    @app.delete("/api/assessments/{item_id}", status_code=204)
    def delete_assessment(item_id: str, user: User):
        owned_assessment(item_id, user)
        with connect(settings) as db:
            db.execute("DELETE FROM assessments WHERE id=? AND user_id=?", (item_id, user["id"]))

    @app.get("/api/assessments/{item_id}/report")
    def report(item_id: str, user: User):
        item = owned_assessment(item_id, user)
        return Response(
            make_pdf(item),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="healthlens-{item["id"]}.pdf"'},
        )

    @app.post("/api/chat")
    async def chat(body: ChatInput, request: Request, user: User):
        limit(request, "chat", 12, 60)
        async with request.app.state.chat_slots:
            return await answer(body.question, body.disease, settings, body.external_consent)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
