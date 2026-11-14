"""Score the model AND the real ``performance.stutter`` rule on the same windows.

    python evaluate.py               # synthetic held-out set, plus real cases if any
    python evaluate.py --real-only   # only real captures from eval/cases/

The rule is not re-implemented here: ``rule_verdict`` builds the same
``RunData`` object the analyzer builds from a run folder, and calls the rule
function registered under ``performance.stutter`` in the workers package. So
the rule is scored exactly as it runs on the server, with its default
thresholds.

Writes ``out/eval.json`` next to the model.

Synthetic scores are a PLUMBING CHECK. The generator, its label definition and
this model were all written together; a high synthetic score proves only that
the parts are connected. Only ``--real-only`` on real, hand-labeled captures
gives a number worth quoting - and there are none yet.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

import model as frame_model
from dataset import DEFAULT_CASES_DIR, DataConfig, Series, load_real_cases, to_windows
from metrics import describe, score

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"

_RULE = None


def stutter_rule():
    """The real rule function, looked up by its code in the rules registry."""
    global _RULE
    if _RULE is None:
        from pcdoctor_analysis.rules import all_rules

        _RULE = next(r.function for r in all_rules() if r.code == "performance.stutter")
    return _RULE


def rule_verdict(frame_ms: np.ndarray) -> bool | None:
    """Run ``performance.stutter`` on one list of frame times.

    Returns True (rule found stutter), False (it passed), or None (it would
    not judge - fewer than 300 frames). It sees only these frames: no frames
    from before the window, which is also all the model sees.
    """
    from pcdoctor_analysis.loader import RunData
    from pcdoctor_analysis.model import Thresholds
    from pcdoctor_analysis.presentmon import FrameData

    times = [float(x) for x in frame_ms]
    elapsed = np.concatenate([[0.0], np.cumsum(times[:-1]) / 1000.0]).tolist()
    run = RunData(frames=FrameData(application="window", frame_times_ms=times, elapsed_s=elapsed))
    findings = stutter_rule()(run, Thresholds())
    if findings is None:
        return None
    return bool(findings)


def rule_predictions(frames: np.ndarray) -> tuple[np.ndarray, int]:
    """The rule's answer for every window, and how many it would not judge.

    A window the rule will not judge counts as "no stutter reported" - that is
    what the user would see.
    """
    verdicts = [rule_verdict(w) for w in frames]
    not_checked = sum(v is None for v in verdicts)
    return np.array([bool(v) for v in verdicts]), not_checked


def by_kind(kinds: list[str], labels, model_pred, rule_pred) -> dict:
    """Scores split by synthetic kind - shows *where* each one goes wrong."""
    groups: dict[str, list[int]] = defaultdict(list)
    for i, kind in enumerate(kinds):
        groups[kind].append(i)
    out = {}
    for kind, idx in sorted(groups.items()):
        out[kind] = {
            "model": score(labels[idx], model_pred[idx]),
            "rule": score(labels[idx], rule_pred[idx]),
        }
    return out


def evaluate_synthetic(net, config: DataConfig, threshold: float, log=print) -> dict:
    windows = config.test_windows()
    model_pred = frame_model.predict_proba(net, windows.frames) >= threshold
    rule_pred, not_checked = rule_predictions(windows.frames)
    result = {
        "set": "synthetic held-out test series (never seen in training)",
        "PLUMBING_CHECK_ONLY": True,
        "series": len(set(windows.series_ids)),
        "model": score(windows.labels, model_pred),
        "rule": score(windows.labels, rule_pred),
        "rule_not_checked": not_checked,
        "model_and_rule_agree": f"{int((model_pred == rule_pred).sum())} of {len(windows)}",
        "by_kind": by_kind(windows.kinds, windows.labels, model_pred, rule_pred),
    }
    log(
        f"Synthetic test set: {len(windows)} windows from {result['series']} series "
        "(PLUMBING CHECK - not a result)"
    )
    log("  " + describe("model", result["model"]))
    log("  " + describe("rule", result["rule"]))
    if not_checked:
        log(f"  (the rule would not judge {not_checked} windows)")
    log(f"  model and rule agree on {result['model_and_rule_agree']} windows")
    log("  by kind (stutter caught / false alarms on smooth):")
    for kind, scores in result["by_kind"].items():
        m, r = scores["model"], scores["rule"]
        log(
            f"    {kind:<16} model {m['true_positives']}/{m['stutter_windows']} caught, "
            f"{m['false_positives']}/{m['smooth_windows']} false   "
            f"rule {r['true_positives']}/{r['stutter_windows']} caught, "
            f"{r['false_positives']}/{r['smooth_windows']} false"
        )
    return result


def evaluate_real(net, cases: list[Series], window: int, threshold: float, log=print) -> dict:
    """Real captures: per window (each inherits its case's label) and per case.

    Per case is the fairer view: the model says "stutter" for a capture when
    any of its windows does; the rule runs once on the whole capture, as the
    analyzer does.
    """
    if not cases:
        log(
            "Real cases: none yet - put labeled captures in eval/cases/ "
            "(see docs/fault-testing.md). Nothing to report."
        )
        return {"cases": 0}
    windows = to_windows(cases, window)
    model_win = frame_model.predict_proba(net, windows.frames) >= threshold
    rule_win, not_checked = rule_predictions(windows.frames)

    case_labels, model_case, rule_case, rows = [], [], [], []
    for s in cases:
        mine = [i for i, sid in enumerate(windows.series_ids) if sid == s.series_id]
        m = bool(model_win[mine].any()) if mine else False
        r = rule_verdict(s.frame_ms)
        case_labels.append(s.label)
        model_case.append(m)
        rule_case.append(bool(r))
        rows.append(
            {"case": s.series_id, "label": s.label, "windows": len(mine), "model": m, "rule": r}
        )
    result = {
        "cases": len(cases),
        "per_case": {
            "model": score(np.array(case_labels), np.array(model_case)),
            "rule": score(np.array(case_labels), np.array(rule_case)),
            "rows": rows,
        },
        "per_window": {
            "model": score(windows.labels, model_win),
            "rule": score(windows.labels, rule_win),
            "rule_not_checked": not_checked,
            "note": "every window carries its whole case's label (rough)",
        },
    }
    log(f"Real cases: {len(cases)} captures, {len(windows)} windows")
    log("  per case:   " + describe("model", result["per_case"]["model"]))
    log("              " + describe("rule", result["per_case"]["rule"]))
    log("  per window: " + describe("model", result["per_window"]["model"]))
    log("              " + describe("rule", result["per_window"]["rule"]))
    for row in rows:
        log(f"    {row['case']}: label {row['label']}, model {row['model']}, rule {row['rule']}")
    return result


def main(argv: list[str] | None = None, log=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where train.py wrote")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--real-only", action="store_true", help="only eval/cases, no synthetic")
    args = parser.parse_args(argv)

    card = json.loads((args.out / "model_card.json").read_text(encoding="utf-8"))
    net = frame_model.load(str(args.out / card["weights"]))
    config = DataConfig.from_dict(card["data_config"])
    threshold = card.get("threshold", 0.5)

    report: dict = {"model_card_created": card["created"], "threshold": threshold}
    if not args.real_only:
        report["synthetic"] = evaluate_synthetic(net, config, threshold, log)
        log("")
    report["real"] = evaluate_real(net, load_real_cases(args.cases), config.window, threshold, log)
    name = "eval_real.json" if args.real_only else "eval.json"
    (args.out / name).write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"\nwrote {args.out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
