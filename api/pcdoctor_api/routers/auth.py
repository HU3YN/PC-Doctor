"""Sign-in endpoints."""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import ClientKey, Master, MaybeAccount, SignedIn
from ..models import Account
from ..services import auth

router = APIRouter(prefix="/api/auth", tags=["auth"])

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class Setup(Credentials):
    setup_code: str = Field(max_length=64)


def set_cookie(response: Response, request: Request, token: str) -> None:
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        auth.COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 24 * 3600,
        httponly=True,  # scripts on the page cannot read it
        samesite="lax",  # other sites cannot make signed-in requests
        secure=https,
        path="/",
    )


@router.get("/status")
def status(db: Db, account: MaybeAccount) -> dict[str, Any]:
    return {
        "setup_needed": not auth.master_exists(db),
        "signed_in": account is not None,
        "username": account.username if account else None,
        "role": account.role if account else None,
    }


@router.post("/setup")
def setup(
    body: Setup, request: Request, response: Response, db: Db, settings: Config, key: ClientKey
) -> dict[str, Any]:
    """Create the master account. Works once, and needs the server's setup code."""
    if auth.master_exists(db):
        raise HTTPException(status_code=409, detail="The master account already exists.")
    if not auth.login_attempts.allow(f"setup:{key}"):
        raise HTTPException(
            status_code=429, detail="Too many attempts. Wait 15 minutes and try again."
        )
    expected = auth.setup_code(settings.data_dir)
    if not hmac.compare_digest(body.setup_code.strip().lower(), expected):
        raise HTTPException(status_code=403, detail="That setup code is not right.")
    if len(body.password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Use a password of at least {auth.MIN_PASSWORD_LENGTH} characters.",
        )
    account = Account(
        username=body.username.strip(), password_hash=auth.hash_password(body.password)
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        # Two set-ups at the same moment: the database allows one master.
        db.rollback()
        raise HTTPException(status_code=409, detail="The master account already exists.") from None
    (settings.data_dir / "setup-code.txt").unlink(missing_ok=True)
    set_cookie(response, request, auth.create_session(db, account))
    return {"signed_in": True, "username": account.username, "role": account.role}


@router.post("/login")
def login(
    body: Credentials, request: Request, response: Response, db: Db, key: ClientKey
) -> dict[str, Any]:
    if not auth.login_attempts.allow(key):
        raise HTTPException(
            status_code=429, detail="Too many attempts. Wait 15 minutes and try again."
        )
    account = db.scalar(select(Account).where(Account.username == body.username.strip()))
    # Check a password even for an unknown user, so both cases take the same time.
    stored = account.password_hash if account else auth.hash_password("not the password")
    if not auth.verify_password(body.password, stored) or account is None:
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    set_cookie(response, request, auth.create_session(db, account))
    return {"signed_in": True, "username": account.username, "role": account.role}


@router.post("/logout")
def logout(request: Request, response: Response, db: Db) -> dict[str, bool]:
    auth.end_session(db, request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"signed_in": False}


@router.post("/logout-everywhere")
def logout_everywhere(response: Response, db: Db, account: SignedIn) -> dict[str, Any]:
    """Sign this account out on every browser, this one included - for a lost
    phone or a session cookie that may have leaked."""
    ended = auth.end_all_sessions(db, account.id)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"signed_in": False, "sessions_ended": ended}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


@router.post("/password")
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    db: Db,
    account: Master,
    key: ClientKey,
) -> dict[str, Any]:
    """Change the master's password. Every other browser is signed out; this
    one gets a fresh session."""
    if not auth.login_attempts.allow(f"password:{key}"):
        raise HTTPException(
            status_code=429, detail="Too many attempts. Wait 15 minutes and try again."
        )
    if not auth.verify_password(body.current_password, account.password_hash):
        raise HTTPException(status_code=403, detail="The current password is not right.")
    if len(body.new_password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Use a password of at least {auth.MIN_PASSWORD_LENGTH} characters.",
        )
    account.password_hash = auth.hash_password(body.new_password)
    db.commit()
    auth.end_all_sessions(db, account.id)
    set_cookie(response, request, auth.create_session(db, account))
    return {"signed_in": True, "username": account.username, "role": account.role}
