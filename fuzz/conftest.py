"""Shared setup for the fuzz tests.

How long a session runs is chosen with environment variables:

    PCDOCTOR_FUZZ_PROFILE    "ci" (default: 100 inputs per property, under a
                             minute in all) or "long" (5,000 per property)
    PCDOCTOR_FUZZ_EXAMPLES   inputs tried per property; overrides the profile
    PCDOCTOR_FUZZ_STRICT     set to 1 to stop tolerating the bugs listed in
                             known_bugs.py (use it to check a fix)

Hypothesis has no "run for N minutes" switch, so a long session is simply a
large number of examples. See README.md for the commands.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings

# Make "import strategies" work wherever pytest is started from.
sys.path.insert(0, str(Path(__file__).parent))

PROFILES = {"ci": 100, "long": 5_000}
PROFILE = os.environ.get("PCDOCTOR_FUZZ_PROFILE", "ci")
if PROFILE not in PROFILES:
    raise ValueError(
        f"PCDOCTOR_FUZZ_PROFILE must be one of {sorted(PROFILES)}, not {PROFILE!r}"
    )
EXAMPLES = int(os.environ.get("PCDOCTOR_FUZZ_EXAMPLES") or PROFILES[PROFILE])

settings.register_profile(
    PROFILE,
    max_examples=EXAMPLES,
    # Some inputs are slow on purpose (a 2 MB file); time is checked by the
    # tests themselves where it matters, not per example by Hypothesis.
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
        HealthCheck.filter_too_much,
    ],
    # Print the failing input as a ready-to-paste reproducer.
    print_blob=True,
)
settings.load_profile(PROFILE)
