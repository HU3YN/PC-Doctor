"""Bugs the fuzzers found that are not fixed yet.

The fuzz tests live in fuzz/ and may not change the code they test. So a bug
that is found is written down three times:

1. here, so the property tests can keep running and find the *next* bug
   instead of stopping at the first one every time;
2. in test_known_bugs.py, as the smallest input that shows it (marked xfail:
   the test starts failing loudly the day the bug is fixed, which is the
   reminder to delete it from this list);
3. in README.md, in the results table.

A bug is matched by exception type and a piece of its message. That is
deliberately narrow, but it is not perfect: a *new* bug that raises the same
error with the same words is hidden too. Run with PCDOCTOR_FUZZ_STRICT=1 from
time to time, and always after a fix.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownBug:
    id: str
    where: str  # file and function
    exception: str  # type name
    message: str  # a piece of the message ("" = any)
    summary: str


KNOWN: tuple[KnownBug, ...] = ()


def match(error: BaseException) -> KnownBug | None:
    name = type(error).__name__
    text = str(error)
    for bug in KNOWN:
        if bug.exception == name and bug.message in text:
            return bug
    return None
