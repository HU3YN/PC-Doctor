"""Helpers the fuzz tests share: a sandbox that notices stray writes, the
checks every analysis result must pass, and the list of known bugs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import known_bugs
from hypothesis import event
from pcdoctor_analysis import AnalysisResult
from pcdoctor_analysis.rules import all_rules

STRICT = os.environ.get("PCDOCTOR_FUZZ_STRICT", "") not in ("", "0")

# ------------------------------------------------------------------ sandbox

# While a sandbox is open, every file the Python process opens for writing is
# recorded here. Python calls the hook for each open(), whatever code does it,
# so a write to /etc or to the home folder cannot slip past unnoticed.
_watching: list[list[str]] = []


def _audit(name: str, args: tuple) -> None:
    if not _watching or name != "open":
        return
    path, mode, flags = args[0], args[1], args[2]
    writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
        isinstance(flags, int)
        and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND)
    )
    if writing and isinstance(path, (str, bytes, os.PathLike)):
        decoded = os.fsdecode(path)
        # Python itself caches compiled modules on first import; that is not
        # the code under test writing.
        if "__pycache__" in Path(decoded).parts:
            return
        _watching[-1].append(decoded)


sys.addaudithook(_audit)


class Sandbox:
    """A throw-away folder with a ``dest`` folder inside it for the code under test."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dest = root / "dest"
        self.dest.mkdir()
        self.opened_for_writing: list[str] = []

    def files(self) -> dict[str, int]:
        """Every file under the sandbox: path relative to the sandbox -> size."""
        return {
            path.relative_to(self.root).as_posix(): path.stat().st_size
            for path in self.root.rglob("*")
            if not path.is_dir()
        }

    def folders(self) -> set[str]:
        return {
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_dir()
        }

    def writes_outside(self, allowed: Path | None = None) -> list[str]:
        """Paths opened for writing that are not inside ``allowed`` (default: dest)."""
        allowed = (allowed or self.dest).resolve()
        outside = []
        for raw in self.opened_for_writing:
            path = Path(raw)
            path = (Path.cwd() / path) if not path.is_absolute() else path
            if not path.resolve().is_relative_to(allowed):
                outside.append(raw)
        return outside


@contextmanager
def sandbox() -> Iterator[Sandbox]:
    """Run code with its working folder inside a fresh sandbox and writes recorded."""
    before = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="pcdoctor-fuzz-") as temp:
        box = Sandbox(Path(temp).resolve())
        cwd = box.root / "cwd"
        cwd.mkdir()
        os.chdir(cwd)  # a relative path in an archive would land here, where we look
        _watching.append(box.opened_for_writing)
        try:
            yield box
        finally:
            _watching.pop()
            os.chdir(before)


# ------------------------------------------------------------ result checks

VERDICTS = {"critical", "warning", "ok"}


def check_result(result: Any) -> None:
    """What must be true of every analysis result, whatever the input was."""
    assert isinstance(result, AnalysisResult), (
        f"not an AnalysisResult: {type(result)!r}"
    )
    assert result.verdict in VERDICTS, result.verdict
    assert isinstance(result.headline, str) and result.headline
    known_codes = {rule.code for rule in all_rules()}
    for finding in result.findings:
        assert finding.code in known_codes, finding.code
        assert isinstance(finding.title, str) and isinstance(finding.summary, str)
    assert {c.status for c in result.checks} <= {"found", "passed", "no_data", "error"}
    assert len(result.checks) == len(known_codes)
    assert set(result.counts) == {"critical", "warning", "info"}
    # The API stores the result as JSON. PostgreSQL refuses NaN and Infinity,
    # so they must never appear (allow_nan=False makes json.dumps refuse too).
    json.dumps(result.to_dict(), allow_nan=False)


def rule_errors(result: AnalysisResult) -> list[str]:
    """Checks that crashed inside the rules engine (it turns them into notes)."""
    return [
        note
        for note in result.notes
        if note.startswith("Check '") and " failed: " in note
    ]


# --------------------------------------------------------------- known bugs


def tolerate(error: BaseException) -> None:
    """Let a known bug pass (recording it); re-raise anything new.

    With PCDOCTOR_FUZZ_STRICT=1 nothing is tolerated: use that to check a fix.
    """
    bug = None if STRICT else known_bugs.match(error)
    if bug is None:
        raise error
    event(f"known bug {bug.id}")
