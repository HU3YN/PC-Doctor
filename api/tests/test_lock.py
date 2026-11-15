"""The Docker image installs from api/requirements.lock: it must cover every
dependency in api/pyproject.toml, or the image would miss one."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

API = Path(__file__).resolve().parents[1]


def name(requirement: str) -> str:
    return re.split(r"[\[<>=!~; ]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def test_the_lock_file_covers_every_dependency():
    project = tomllib.loads((API / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    wanted = {name(d) for d in project["dependencies"]} - {"pcdoctor-analysis"}
    for extra in ("photo", "ai", "queue"):  # what api/Dockerfile installs
        wanted |= {name(d) for d in project["optional-dependencies"][extra]}
    lock = (API / "requirements.lock").read_text(encoding="utf-8")
    locked = {m.group(1).lower() for m in re.finditer(r"^([A-Za-z0-9_.-]+)==", lock, re.M)}
    missing = wanted - locked
    assert not missing, f"run python api/lock.py: {sorted(missing)} not in requirements.lock"
    # Every pinned package carries a hash, so pip --require-hashes can check it.
    blocks = re.findall(
        r"^[A-Za-z0-9_.-]+==\S+(?: ;[^\\\n]*)?((?:\s*\\\n\s+--hash=sha256:[0-9a-f]{64})+)",
        lock,
        re.M,
    )
    assert len(blocks) == len(re.findall(r"^[A-Za-z0-9_.-]+==", lock, re.M))
