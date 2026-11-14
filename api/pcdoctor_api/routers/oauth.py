"""Sign-in with Discord or Google, and the accounts that come from it."""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Master, MaybeAccount, SignedIn
from ..models import Account, Identity
from ..services import auth
from ..services import oauth as oauth_service
from .auth import set_cookie

router = APIRouter(prefix="/api", tags=["auth"])

Db = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]

FLOW_COOKIE = "pcdoctor_oauth"
FLOW_SECONDS = 600
FLOW_PATH = "/api/auth/oauth"


def back(settings: Settings, problem: str = "") -> RedirectResponse:
    """Send the browser back to the dashboard, with a short reason if it failed."""
    target = settings.public_url.rstrip("/") + ("/login?problem=" + problem if problem else "/")
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    return response


@router.get("/auth/oauth")
def providers(settings: Config) -> dict[str, Any]:
    return {
        "providers": [
            {"name": p.name, "label": p.label} for p in oauth_service.configured(settings)
        ],
        "signup": settings.oauth_signup,
    }


@router.get("/auth/oauth/{name}/start")
def start(
    name: str,
    request: Request,
    settings: Config,
    account: MaybeAccount,
    intent: Annotated[str, Query(pattern="^(login|link)$")] = "login",
) -> RedirectResponse:
    try:
        provider = oauth_service.get_provider(settings, name)
    except oauth_service.OAuthError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    if intent == "link" and account is None:
        raise HTTPException(status_code=401, detail="Sign in first, then link.")
    state, verifier = secrets.token_urlsafe(24), oauth_service.new_verifier()
    response = RedirectResponse(
        oauth_service.authorize_url(settings, provider, state, verifier), status_code=303
    )
    response.set_cookie(
        FLOW_COOKIE,
        f"{state}.{verifier}.{intent}",
        max_age=FLOW_SECONDS,
        httponly=True,
        samesite="lax",  # must survive the provider sending the browser back
        secure=settings.public_url.startswith("https://"),
        path=FLOW_PATH,
    )
    return response


def member_for(db: Session, provider: str, subject: str) -> Account:
    """A new member account. Its name is ours, not the person's."""
    account = Account(
        username=f"{provider}-{secrets.token_hex(4)}",
        password_hash="oauth-only",  # not a valid hash, so no password ever matches
        role="member",
    )
    account.identities.append(Identity(provider=provider, subject=subject))
    db.add(account)
    db.commit()
    return account


@router.get("/auth/oauth/{name}/callback")
def callback(
    name: str,
    request: Request,
    db: Db,
    settings: Config,
    account: MaybeAccount,
    code: str = "",
    state: str = "",
) -> RedirectResponse:
    try:
        provider = oauth_service.get_provider(settings, name)
    except oauth_service.OAuthError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    parts = request.cookies.get(FLOW_COOKIE, "").split(".")
    if len(parts) != 3 or not code or not state:
        return back(settings, "expired")
    expected_state, verifier, intent = parts
    if not hmac.compare_digest(state.encode(), expected_state.encode()):
        return back(settings, "expired")  # not the sign-in this browser started
    try:
        subject = oauth_service.fetch_subject(settings, provider, code, verifier)
    except oauth_service.OAuthError:
        return back(settings, "provider")

    identity = db.scalar(
        select(Identity).where(Identity.provider == provider.name, Identity.subject == subject)
    )
    if intent == "link":
        if account is None:
            return back(settings, "expired")
        if identity is not None and identity.account_id != account.id:
            return back(settings, "taken")
        if identity is None:
            db.add(Identity(account_id=account.id, provider=provider.name, subject=subject))
            db.commit()
        return back(settings)

    if identity is not None:
        target = identity.account
    elif settings.oauth_signup and auth.master_exists(db):
        target = member_for(db, provider.name, subject)
    else:
        return back(settings, "not_linked")
    response = back(settings)
    set_cookie(response, request, auth.create_session(db, target))
    return response


@router.get("/accounts")
def list_accounts(db: Db, _: Master) -> list[dict[str, Any]]:
    accounts = db.scalars(
        select(Account).options(selectinload(Account.identities)).order_by(Account.id)
    )
    return [
        {
            "id": a.id,
            "username": a.username,
            "role": a.role,
            "created_at": a.created_at,
            "providers": sorted({i.provider for i in a.identities}),
        }
        for a in accounts
    ]


@router.delete("/accounts/{account_id}", status_code=204)
def remove_account(account_id: int, db: Db, master: Master) -> None:
    """Remove a member. Their runs stay (the master can still see them)."""
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    if account.id == master.id or account.role == "master":
        raise HTTPException(status_code=409, detail="The master account cannot be removed.")
    db.delete(account)
    db.commit()


@router.get("/auth/identities")
def my_identities(account: SignedIn) -> list[dict[str, Any]]:
    return [
        {"id": i.id, "provider": i.provider, "linked_at": i.created_at} for i in account.identities
    ]


@router.delete("/auth/identities/{identity_id}", status_code=204)
def unlink(identity_id: int, db: Db, account: SignedIn) -> None:
    identity = db.get(Identity, identity_id)
    if identity is None or identity.account_id != account.id:
        raise HTTPException(status_code=404, detail="Not found.")
    if account.role != "master" and len(account.identities) == 1:
        raise HTTPException(
            status_code=409, detail="This is your only way to sign in, so it cannot be unlinked."
        )
    db.delete(identity)
    db.commit()
