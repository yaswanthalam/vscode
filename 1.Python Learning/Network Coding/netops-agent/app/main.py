"""HTTP layer. Run with:  uvicorn app.main:app --host 127.0.0.1 --port 8000"""
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import api, settings

app = FastAPI(title="NetOps Read-Only Agent")
STATIC = settings.BASE_DIR / "static"


class CommandIn(BaseModel):
    device: str
    command: str
    purpose: str = ""
    acknowledge_warning: bool = False


class QuestionIn(BaseModel):
    question: str


def _user(principal, forwarded) -> str:
    # App Service / Container Apps "Easy Auth" sets X-MS-CLIENT-PRINCIPAL-NAME;
    # an auth reverse proxy can set X-Forwarded-User instead.
    try:
        return api.authorise(principal or forwarded)
    except api.Forbidden as exc:
        raise HTTPException(403, str(exc))


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except api.BadRequest as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/info")
def info(x_ms_client_principal_name: str | None = Header(None), x_forwarded_user: str | None = Header(None)):
    user = _user(x_ms_client_principal_name, x_forwarded_user)
    return {**api.info(), "user": user}


@app.post("/api/validate")
def validate(body: CommandIn, x_ms_client_principal_name: str | None = Header(None),
             x_forwarded_user: str | None = Header(None)):
    user = _user(x_ms_client_principal_name, x_forwarded_user)
    return _call(api.validate, user, body.device, body.command, body.purpose)


@app.post("/api/run")
def run(body: CommandIn, x_ms_client_principal_name: str | None = Header(None),
        x_forwarded_user: str | None = Header(None)):
    user = _user(x_ms_client_principal_name, x_forwarded_user)
    return _call(api.run, user, body.device, body.command, body.purpose, body.acknowledge_warning)


@app.post("/api/ask")
def ask(body: QuestionIn, x_ms_client_principal_name: str | None = Header(None),
        x_forwarded_user: str | None = Header(None)):
    user = _user(x_ms_client_principal_name, x_forwarded_user)
    return _call(api.ask, user, body.question)


@app.get("/api/audit")
def audit(limit: int = 100, x_ms_client_principal_name: str | None = Header(None),
          x_forwarded_user: str | None = Header(None)):
    _user(x_ms_client_principal_name, x_forwarded_user)
    return api.audit_tail(limit)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
