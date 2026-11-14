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


def require_account(account: Annotated[Account | None, Depends(current_account)]) -> Account:
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in to do this.")
    return account


def require_master(account: Annotated[Account, Depends(require_account)]) -> Account:
    # Being signed in is not enough: members see only their own runs.
    if account.role != "master":
        raise HTTPException(status_code=403, detail="Only the master account can do this.")
    return account


def client_key(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """Who to count a request against for rate limits: the caller's address."""
    if settings.trust_proxy:
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [part for part in forwarded if part]
        if forwarded:
            # Each of our proxies appended the address it saw. Counting from
            # the right skips our own proxies; never read further left than
            # that, because the caller can write whatever it likes there.
            return forwarded[-min(settings.proxy_hops, len(forwarded))]
    return request.client.host if request.client else "unknown"


Master = Annotated[Account, Depends(require_master)]
SignedIn = Annotated[Account, Depends(require_account)]
MaybeAccount = Annotated[Account | None, Depends(current_account)]
ClientKey = Annotated[str, Depends(client_key)]
