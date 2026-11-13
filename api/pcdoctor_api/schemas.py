"""Request and response shapes for the API."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pcdoctor_analysis.model import CATEGORIES
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .services.similarity import normalize_codes

STATUSES: dict[str, str] = {
    "open": "Open - still working on it",
    "fixed": "Fixed",
    "not_fixed": "Not fixed",
}
DEVICE_TYPES: dict[str, str] = {
    "gaming_pc": "Gaming PC",
    "workstation": "Workstation",
    "server": "Server",
    "laptop": "Laptop",
    "office_pc": "Office / home PC",
    "other": "Other",
}

Status = Literal["open", "fixed", "not_fixed"]
DeviceType = Literal["gaming_pc", "workstation", "server", "laptop", "office_pc", "other"]


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    category: str
    severity: str
    title: str
    summary: str
    next_checks: list[str]
    evidence: dict[str, Any]
    error_codes: list[str]


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    captured_at: datetime | None
    label: str
    mode: str
    verdict: str
    headline: str
    critical_count: int
    warning_count: int
    info_count: int
    cpu: str | None
    gpu: str | None
    ram_gb: int | None
    avg_fps: float | None
    fps_1pct_low: float | None
    is_demo: bool
    rules_version: str
    source: str = "master"


class RunList(BaseModel):
    items: list[RunSummary]
    total: int


class WorkLogBrief(BaseModel):
    """A work-log entry as shown in lists and as a match."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_on: date
    title: str
    status: str
    category: str
    device_type: str
    device: str
    root_cause: str
    fix: str
    components: list[str]
    error_codes: list[str]
    is_demo: bool
    run_id: str | None


class SimilarCase(BaseModel):
    entry: WorkLogBrief
    score: float
    reasons: list[str]


class RunDetail(RunSummary):
    notes: str
    collector_version: str
    file_bytes: int
    rules_outdated: bool  # analysed with older rules than the server has now
    findings: list[FindingOut]
    checks: list[dict[str, Any]]
    device: dict[str, Any]
    frame_stats: dict[str, Any] | None
    sensor_stats: dict[str, Any]
    analysis_notes: list[str]
    has_frames: bool
    has_sensors: bool
    similar_cases: list[SimilarCase]
    work_log: list[WorkLogBrief]  # entries logged from this run


class RunUploaded(BaseModel):
    run: RunSummary
    duplicate: bool  # True = this exact file was already uploaded
    # Guests only: the key of the private link to this one run (/r/<key>).
    share_key: str | None = None


class RunPatch(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=20000)


def _clean_list(values: list[str], max_items: int, max_length: int) -> list[str]:
    out: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value)).strip()[:max_length]
        if text and text.lower() not in (v.lower() for v in out):
            out.append(text)
    return out[:max_items]


class WorkLogFields(BaseModel):
    """Fields shared by create and update. Only the title is required."""

    title: str = Field(min_length=1, max_length=200)
    occurred_on: date | None = None  # defaults to today
    status: Status = "open"
    category: str = "other"
    device_type: DeviceType = "other"
    device: str = Field(default="", max_length=300)
    symptoms: str = Field(default="", max_length=20000)
    steps: str = Field(default="", max_length=20000)
    root_cause: str = Field(default="", max_length=20000)
    fix: str = Field(default="", max_length=20000)
    components: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    reference: str = Field(default="", max_length=80)
    minutes_spent: int | None = Field(default=None, ge=0, le=100000)
    run_id: str | None = None

    @field_validator("title", "device", "reference")
    @classmethod
    def _one_line(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("The title cannot be blank.")
        return value

    @field_validator("symptoms", "steps", "root_cause", "fix")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError(f"Unknown category. Use one of: {', '.join(CATEGORIES)}")
        return value

    @field_validator("components")
    @classmethod
    def _clean_components(cls, value: list[str]) -> list[str]:
        return _clean_list(value, max_items=30, max_length=80)

    @field_validator("error_codes")
    @classmethod
    def _clean_codes(cls, value: list[str]) -> list[str]:
        return normalize_codes(_clean_list(value, max_items=30, max_length=40))

    @field_validator("run_id")
    @classmethod
    def _blank_run_is_none(cls, value: str | None) -> str | None:
        return value or None


class WorkLogCreate(WorkLogFields):
    pass


class WorkLogUpdate(WorkLogFields):
    pass


class WorkLogOut(WorkLogBrief):
    created_at: datetime
    updated_at: datetime
    symptoms: str
    steps: str
    reference: str
    minutes_spent: int | None
    run_label: str | None = None
    # Things in the text that look like customer data (see docs/privacy.md).
    privacy_warnings: list[str] = Field(default_factory=list)


class WorkLogList(BaseModel):
    items: list[WorkLogOut]
    total: int


class SimilarQuery(BaseModel):
    text: str = Field(default="", max_length=20000)
    codes: list[str] = Field(default_factory=list)
    category: str | None = None
    parts: list[str] = Field(default_factory=list)
    exclude_id: int | None = None
    limit: int = Field(default=5, ge=1, le=20)


class ImportResult(BaseModel):
    imported: int
    skipped: int  # already in the log


class DemoResult(BaseModel):
    runs: int
    work_log: int
