"""ml/leds/ is a folder of scripts, not a package, so the tests add it to the import path."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model  # noqa: E402

model.limit_threads()  # the test machine may be shared
