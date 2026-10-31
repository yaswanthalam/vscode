import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request

from app.db import connect

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def limit(request, scope, maximum=30, seconds=60):
    settings = request.app.state.settings
    # Do not trust client-supplied forwarding headers.
    address = request.client.host if request.client else "unknown"
    bucket = digest(scope + ":" + address)
    now = time.time()
    with connect(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM rate_limits WHERE reset < ?", (now,))
        row = db.execute("SELECT count FROM rate_limits WHERE bucket=?", (bucket,)).fetchone()
        if row and row["count"] >= maximum:
            raise HTTPException(
                429, "Too many requests; try again later", headers={"Retry-After": str(seconds)}
            )
        db.execute(
            """INSERT INTO rate_limits VALUES (?, 1, ?)
               ON CONFLICT(bucket) DO UPDATE SET count=count+1""",
            (bucket, now + seconds),
        )


def current_user(request: Request):
    token = request.cookies.get("healthlens_session", "")
    with connect(request.app.state.settings) as db:
        db.execute("DELETE FROM sessions WHERE expires <= ?", (time.time(),))
        row = db.execute(
            """SELECT users.id, users.username FROM users
               JOIN sessions ON users.id=sessions.user_id
               WHERE token_hash=? AND expires>?""",
            (digest(token), time.time()),
        ).fetchone()
    if not row:
        raise HTTPException(401, "Please sign in")
    return dict(row)


def verify_password(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def create_session(response, request, user_id):
    settings = request.app.state.settings
    token = secrets.token_urlsafe(32)
    with connect(settings) as db:
        old = request.cookies.get("healthlens_session", "")
        db.execute(
            "DELETE FROM sessions WHERE token_hash=? OR expires<=?", (digest(old), time.time())
        )
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?)",
            (digest(token), user_id, time.time() + settings.session_hours * 3600),
        )
    response.set_cookie(
        "healthlens_session",
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
