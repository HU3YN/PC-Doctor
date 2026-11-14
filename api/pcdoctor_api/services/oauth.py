"""Sign-in with Discord or Google: the OAuth 2.0 authorization code flow, with PKCE.

The steps, so the code below reads easily:

1. /start      We make a random ``state`` and a random ``verifier``, keep both
               in a short-lived HttpOnly cookie, and send the browser to the
               provider with the state and a hash of the verifier (the
               "challenge").
2. the person signs in at the provider and approves.
3. /callback   The provider sends the browser back with a ``code`` and our
               state. The state must match the cookie - otherwise someone
               else started this sign-in (a forged request) and we stop.
4. We swap the code for an access token, server to server, sending our client
   secret and the verifier. Only whoever started the flow knows the verifier,
   so a stolen code is useless.
5. We ask the provider who the token belongs to and keep one thing: their id.

No name, email or picture is requested or stored (docs/privacy.md).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from ..config import Settings


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str  # the least that identifies the person
    subject_field: str  # where their id is in the userinfo answer


PROVIDERS: dict[str, Provider] = {
    "discord": Provider(
        name="discord",
        label="Discord",
        authorize_url="https://discord.com/oauth2/authorize",
        token_url="https://discord.com/api/oauth2/token",
        userinfo_url="https://discord.com/api/users/@me",
        scope="identify",
        subject_field="id",
    ),
    "google": Provider(
        name="google",
        label="Google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid",
        subject_field="sub",
    ),
}


class OAuthError(RuntimeError):
    """The sign-in could not be completed. The message is safe to show."""


def credentials(settings: Settings, name: str) -> tuple[str, str]:
    return {
        "discord": (settings.discord_client_id, settings.discord_client_secret),
        "google": (settings.google_client_id, settings.google_client_secret),
    }.get(name, ("", ""))


def configured(settings: Settings) -> list[Provider]:
    """Providers that can be used: both keys set, and we know our own address."""
    if not settings.public_url:
        return []
    return [p for p in PROVIDERS.values() if all(credentials(settings, p.name))]


def get_provider(settings: Settings, name: str) -> Provider:
    for provider in configured(settings):
        if provider.name == name:
            return provider
    raise OAuthError("That sign-in is not set up on this server.")


def redirect_uri(settings: Settings, provider: Provider) -> str:
    return f"{settings.public_url.rstrip('/')}/api/auth/oauth/{provider.name}/callback"


def new_verifier() -> str:
    return secrets.token_urlsafe(48)


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(settings: Settings, provider: Provider, state: str, verifier: str) -> str:
    client_id, _ = credentials(settings, provider.name)
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(settings, provider),
        "scope": provider.scope,
        "state": state,
        "code_challenge": challenge_for(verifier),
        "code_challenge_method": "S256",
    }
    return f"{provider.authorize_url}?{urlencode(query)}"


def http_client() -> httpx.Client:
    """Replaced in tests by a client that never leaves the process."""
    return httpx.Client(timeout=10.0, follow_redirects=False)


def fetch_subject(settings: Settings, provider: Provider, code: str, verifier: str) -> str:
    """Steps 4 and 5: swap the code for a token, then ask whose it is."""
    client_id, client_secret = credentials(settings, provider.name)
    try:
        with http_client() as client:
            token_reply = client.post(
                provider.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri(settings, provider),
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
            if token_reply.status_code != 200:
                raise OAuthError(f"{provider.label} did not accept the sign-in. Try again.")
            token = token_reply.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise OAuthError(f"{provider.label} did not accept the sign-in. Try again.")
            who = client.get(provider.userinfo_url, headers={"Authorization": f"Bearer {token}"})
            if who.status_code != 200:
                raise OAuthError(f"{provider.label} did not say who signed in. Try again.")
            subject = who.json().get(provider.subject_field)
    except (httpx.HTTPError, ValueError):
        raise OAuthError(f"{provider.label} could not be reached. Try again.") from None
    # The token is not kept: we only needed it for that one question.
    if not isinstance(subject, (str, int)) or not str(subject).strip():
        raise OAuthError(f"{provider.label} did not say who signed in. Try again.")
    return str(subject)[:128]
