"""Shared request dependencies: who is asking."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .models import Account
from .services import auth


def current_account(request: Request, db: Annotated[Session, Depends(get_db)]) -> Account | None:
    return auth.account_for(db, request.cookies.get(auth.COOKIE))


def require_master(account: Annotated[Account | None, Depends(current_account)]) -> Account:
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in to do this.")
    return account


def client_key(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """Who to count a request against for rate limits: the caller's address."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()  # the entry our own proxy added
    return request.client.host if request.client else "unknown"


Master = Annotated[Account, Depends(require_master)]
MaybeAccount = Annotated[Account | None, Depends(current_account)]
ClientKey = Annotated[str, Depends(client_key)]
