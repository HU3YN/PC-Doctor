"""The FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import __version__
from .config import Settings, get_settings
from .db import get_db, migrate
from .routers import assist, auth, inbox, intake, reference, runs, worklog
from .services import auth as auth_service


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
    app.include_router(reference.router)
    app.include_router(runs.router)
    app.include_router(worklog.router)
    app.include_router(intake.router)
    app.include_router(runs.shared)
    app.include_router(auth.router)
    app.include_router(inbox.router)
    app.include_router(assist.router)

    dist = settings.web_dist
    if dist is None:
        # Running from a checkout: use web/dist if the dashboard has been built.
        guess = Path(__file__).resolve().parents[2] / "web" / "dist"
        dist = guess if (guess / "index.html").is_file() else None
    if dist is not None and (dist / "index.html").is_file():
        mount_dashboard(app, dist)
    return app


app = create_app()
