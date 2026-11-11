"""The rules engine: small functions that each look for one kind of fault.

A rule gets the loaded run and the thresholds and returns:

    None            it had no data to judge (shown as "not checked")
    []              it looked and found nothing wrong (shown as "passed")
    [Finding, ...]  what it found

Each rule owns exactly one finding code, so "how many fault types can the
tool detect" is simply the number of rules.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..loader import RunData
from ..model import Finding, Thresholds

RuleFunction = Callable[[RunData, Thresholds], "list[Finding] | None"]


@dataclass(frozen=True)
class Rule:
    code: str
    category: str
    title: str  # what the check is called in the "checks" list
    detects: str  # one sentence: what fault this finds
    needs: str  # what data it needs, in plain words
    function: RuleFunction


_REGISTRY: dict[str, Rule] = {}


def rule(code: str, category: str, title: str, detects: str, needs: str):
    """Register a rule. The decorated function must only emit findings with ``code``."""

    def decorator(function: RuleFunction) -> RuleFunction:
        if code in _REGISTRY:
            raise ValueError(f"Duplicate rule code: {code}")
        _REGISTRY[code] = Rule(code, category, title, detects, needs, function)
        return function

    return decorator


def all_rules() -> list[Rule]:
    _load()
    return list(_REGISTRY.values())


def _load() -> None:
    # Importing the modules runs their @rule decorators.
    from . import events, performance, storage, system, thermal  # noqa: F401


_CAUSE_ORDER = {
    name: position
    for position, name in enumerate(
        ("storage", "memory", "cpu", "power", "gpu", "thermal", "motherboard", "driver", "os")
    )
}
# How the PC is set up, as opposed to something failing or measured going
# wrong. These explain a problem but are rarely the headline.
_SETUP_CODES = frozenset(
    {
        "memory.single_channel",
        "memory.slow_speed",
        "memory.mixed_modules",
        "driver.gpu_old",
    }
)


# "3 blue screen(s)" -> "3 blue screens", "1 time(s)" -> "1 time".
_COUNTED = re.compile(r"\b(\d+)(x?) ([^().:;,\d]*?)\((s|es)\)")


def tidy_plurals(text: str) -> str:
    """Rules write "N thing(s)"; readers get the right form for N."""
    return _COUNTED.sub(lambda m: f"{m[1]}{m[2]} {m[3]}{'' if m[1] == '1' else m[4]}", text)


def _order(finding: Finding) -> tuple[int, int]:
    """Worst first. Within a severity: faults, then setup, then symptoms.

    A failing disk or an overheating CPU is the headline; the stutter it
    causes is not.
    """
    if finding.category == "performance":
        position = 200
    elif finding.code in _SETUP_CODES:
        position = 100
    else:
        position = _CAUSE_ORDER.get(finding.category, 50)
    return (-finding.severity.rank, position)


@dataclass
class Check:
    code: str
    category: str
    title: str
    status: str  # "found" | "passed" | "no_data" | "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "category": self.category,
            "title": self.title,
            "status": self.status,
        }


def run_rules(
    run: RunData, thresholds: Thresholds | None = None
) -> tuple[list[Finding], list[Check], list[str]]:
    """Run every rule. One broken rule never stops the others."""
    thresholds = thresholds or Thresholds()
    findings: list[Finding] = []
    checks: list[Check] = []
    errors: list[str] = []
    for entry in all_rules():
        try:
            result = entry.function(run, thresholds)
        except Exception as error:  # noqa: BLE001 - a rule bug must not lose the run
            errors.append(f"Check '{entry.title}' failed: {error.__class__.__name__}: {error}")
            checks.append(Check(entry.code, entry.category, entry.title, "error"))
            continue
        if result is None:
            status = "no_data"
        elif result:
            status = "found"
            for finding in result:
                if finding.code != entry.code:
                    raise AssertionError(
                        f"Rule {entry.code} emitted a finding with code {finding.code}"
                    )
                finding.title = tidy_plurals(finding.title)
                finding.summary = tidy_plurals(finding.summary)
            findings.extend(result)
        else:
            status = "passed"
        checks.append(Check(entry.code, entry.category, entry.title, status))
    findings.sort(key=_order)
    return findings, checks, errors
