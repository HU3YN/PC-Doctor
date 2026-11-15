"""PC Doctor analysis: turn a collector run folder into findings.

The public entry points are :func:`analyze_run_dir` and :func:`analyze_run`.
"""

from .analyze import AnalysisResult, analyze_run, analyze_run_dir
from .loader import RunData, load_run_dir
from .model import CATEGORIES, Finding, Severity

__version__ = "0.1.0"

# Bump when a rule or threshold changes, so stored results can be told apart
# from results made with newer rules (the API offers "re-analyze" for this).
RULES_VERSION = "2026.11.2"

__all__ = [
    "CATEGORIES",
    "RULES_VERSION",
    "AnalysisResult",
    "Finding",
    "RunData",
    "Severity",
    "analyze_run",
    "analyze_run_dir",
    "load_run_dir",
]
