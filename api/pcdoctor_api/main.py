"""The FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import __version__, logs, metrics
from .config import Settings, get_settings
from .db import get_db, migrate
from .routers import assist, auth, inbox, intake, live, oauth, reference, runs, worklog
from .services import auth as auth_service
from .services import live as live_service
from .services import oauth as oauth_service


@contextmanager
def _session() -> Iterator[Session]:
    yield from get_db()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    settings.photos_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_migrate:
        migrate()
    auth_service.use_shared_limits(settings.redis_url)
    auth_service.bot_uploads.limit = settings.bot_uploads_per_hour
    live_service.use_redis(settings.redis_url)
    if settings.metrics_token and metrics.weak_token(settings.metrics_token):
        print(
            "PC Doctor: PCDOCTOR_METRICS_TOKEN is too short or a well-known value, so "
            "/api/metrics is off. Use 16+ random characters (see .env.example).",
            flush=True,
        )
    if settings.public_url and not oauth_service.public_url_ok(settings.public_url):
        print(
            "PC Doctor: PCDOCTOR_PUBLIC_URL must be https:// (plain http:// only to this "
            "computer or a private network address), so Discord/Google sign-in is off.",
            flush=True,
        )
    # Until the master account exists, make sure the setup code does, and show
    # it where only someone at the server can see it.
    try:
        with _session() as session:
            if not auth_service.master_exists(session):
                code = auth_service.setup_code(settings.data_dir)
                print(f"PC Doctor: no master account yet. Setup code: {code}", flush=True)
    except Exception as error:  # noqa: BLE001 - never block start-up over this
        print(f"PC Doctor: could not prepare the setup code ({error})", flush=True)
    yield


# Sent with every response (web/security-headers.conf has the same for nginx).
# The dashboard loads nothing from other sites, so the policy can be strict:
# no inline scripts, no frames, no plugins. Images may be data: URLs (the QR
# code) and blob: URLs (photo previews).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # A private link (/r/<key>) must never travel to another site as a referrer.
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "geolocation=(), microphone=(), payment=(), usb=()",
}


async def security_headers(request: Request, call_next):  # noqa: ANN001, ANN201
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    # The API's own documentation page loads its scripts from a CDN.
    if request.url.path != "/api/docs":
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    return response


def mount_dashboard(app: FastAPI, dist: Path) -> None:
    """Serve the built dashboard, so one process is the whole app.

    Any path that is not a file falls back to index.html, because the
    dashboard does its own routing in the browser (/runs/abc, /worklog, ...).
    """
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logs.install()  # private links and tokens never reach the access log
    app = FastAPI(
        title="PC Doctor",
        version=__version__,
        description="Stores collector runs, diagnoses them, and keeps the technician's work log.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.middleware("http")(metrics.record_request)
    app.middleware("http")(security_headers)
    app.include_router(metrics.router)
    app.include_router(reference.router)
    app.include_router(runs.router)
    app.include_router(worklog.router)
    app.include_router(intake.router)
    app.include_router(runs.shared)
    app.include_router(runs.mine)
    app.include_router(oauth.router)
    app.include_router(auth.router)
    app.include_router(inbox.router)
    app.include_router(assist.router)
    app.include_router(live.router)

    dist = settings.web_dist
    if dist is None:
        # Running from a checkout: use web/dist if the dashboard has been built.
        guess = Path(__file__).resolve().parents[2] / "web" / "dist"
        dist = guess if (guess / "index.html").is_file() else None
    if dist is not None and (dist / "index.html").is_file():
        mount_dashboard(app, dist)
    return app


app = create_app()
