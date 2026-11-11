"""Settings, read from environment variables (and a git-ignored .env file).

Nothing secret has a default here. See .env.example for every option.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PCDOCTOR_", env_file=".env", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
