"""Shared test set-up.

ml/frames/ is a folder of scripts, not a package, so the tests add it to the
import path.

PyTorch runs on one CPU thread in the tests: the models here are tiny, so
splitting the work across threads costs more than it saves, and on a busy
machine (a shared CI runner) extra threads make the run times jump around.
"""

import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
torch.set_num_threads(1)
