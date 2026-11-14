"""Settings, read from environment variables (and a git-ignored .env file).

Nothing secret has a default here. See .env.example for every option.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PCDOCTOR_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # Where uploaded runs and (by default) the local database live.
    data_dir: Path = Path("data")
    # SQLAlchemy URL. Empty = a SQLite file in data_dir, so the API runs with
    # no setup at all. Docker Compose sets this to the PostgreSQL service.
    database_url: str = ""
    # Largest upload accepted, and the largest it may unpack to.
    max_upload_mb: int = Field(default=200, ge=1, le=2048)
    max_unpacked_mb: int = Field(default=1024, ge=1, le=8192)
    # Create or upgrade the database tables on start-up.
    auto_migrate: bool = True
    # Folder with the built dashboard (web/dist). When it exists, the API
    # serves it, so one process is the whole app.
    web_dist: Path | None = None
    # Folder holding the Windows collector, offered for download from the
    # dashboard. Found automatically when running from a checkout.
    collector_dir: Path | None = None
    # True when a reverse proxy we run (nginx in Docker Compose) sits in front
    # and sets X-Forwarded-For. Used only for rate limits.
    trust_proxy: bool = False
    # How many proxies we run in front of the API, each adding one address to
    # X-Forwarded-For. Docker Compose: 1 (nginx). k3s: 2 (Traefik, then nginx).
    # The caller's address is that many places from the right; anything further
    # left was sent by the caller and cannot be trusted.
    proxy_hops: int = Field(default=1, ge=1, le=5)
    # Key for the AI helper (drafting work-log entries, describing photos).
    # Empty = the helper is switched off and everything else works as before.
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    ai_model: str = "claude-sonnet-5-5"
    # --- Scale-out (Phase 3). All optional: one process still runs everything.
    # Redis: the job queue the Go upload service fills, and shared rate limits.
    redis_url: str = ""
    # Folder the upload service writes checked uploads into (a shared volume).
    spool_dir: Path | None = None
    # Prometheus may read /api/metrics only with this token. Empty = no metrics.
    metrics_token: str = ""
    # --- Sign-in with Discord or Google (Phase 4). Optional.
    # The address people use to reach this server, e.g. https://pcdoctor.example.com.
    # OAuth needs it to build the "come back here" address; it is never guessed
    # from the request.
    public_url: str = ""
    discord_client_id: str = ""
    discord_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    # False: only identities the master has linked can sign in. True: anyone
    # who signs in gets their own member account (sees only their own runs).
    oauth_signup: bool = False
    # A Discord webhook that is told when a guest uploads a run (headline only).
    notify_webhook_url: str = ""
    # A shared secret for the Discord bot (bot/). An upload that carries it in
    # the X-PCDoctor-Bot-Token header is counted against a separate, higher
    # limit, because one bot uploads for a whole server from one address. It
    # changes nothing else: the upload is still a guest upload and the token
    # cannot read anything. Empty = no bot limit, the bot counts as one guest.
    bot_token: str = ""
    bot_uploads_per_hour: int = Field(default=300, ge=1, le=100_000)
    # Extra origins allowed to call the API from a browser (comma separated).
    # The Vite dev server proxies /api, so this is normally empty.
    cors_origins: list[str] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url.strip()
        if not url:
            return f"sqlite:///{(self.data_dir / 'pcdoctor.sqlite3').as_posix()}"
        # Accept the short forms people paste, and always use psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def spool(self) -> Path:
        return self.spool_dir or self.data_dir / "spool"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"


@lru_cache
def get_settings() -> Settings:
    return Settings()
