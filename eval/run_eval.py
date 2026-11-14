"""Evaluation harness: how often does the diagnosis name the right cause?

    python eval/run_eval.py              every labeled case
    python eval/run_eval.py --real-only  only real captures (the number that counts)

A case is a run folder plus the finding codes a correct diagnosis must contain.

  * Real cases live in eval/cases/<name>/ - a collector run folder with a
    label.json next to its files:
        {"expected": ["thermal.cpu_hot"], "must_not": ["storage.disk_unhealthy"],
         "description": "Fan capped at 30%, Cinebench loop", "machine": "my desktop"}
  * Synthetic cases come from pcdoctor_analysis.synth. They prove the plumbing
    works. They are NOT evidence of accuracy - the rules were written against
    them - so they are reported separately and must never be quoted as a result.

A case passes when every expected code is found and no "must_not" code is.
Record the real-case score in docs/results.md before and after each change.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from pcdoctor_analysis import RULES_VERSION, analyze_run_dir, synth

CASES = Path(__file__).parent / "cases"


def judge(found: set[str], expected: list[str], must_not: list[str]) -> tuple[bool, list[str]]:
    problems = [f"missed {code}" for code in expected if code not in found]
    problems += [f"wrongly reported {code}" for code in must_not if code in found]
    return not problems, problems


def real_cases() -> list[tuple[str, Path, dict]]:
    cases = []
    for label_file in sorted(CASES.glob("*/label.json")):
        cases.append(
            (label_file.parent.name, label_file.parent, json.loads(label_file.read_text()))
        )
    return cases


def run(real_only: bool) -> int:
    results: dict[str, list[tuple[str, bool, list[str]]]] = {"real": [], "synthetic": []}
    for name, folder, label in real_cases():
        found = {f.code for f in analyze_run_dir(folder).findings}
        ok, problems = judge(found, label.get("expected", []), label.get("must_not", []))
        results["real"].append((name, ok, problems))
    if not real_only:
        for sample in synth.build_all():
            with tempfile.TemporaryDirectory() as folder:
                sample.write(folder)
                found = {f.code for f in analyze_run_dir(folder).findings}
            ok, problems = judge(found, sample.expected, [])
            results["synthetic"].append((sample.name, ok, problems))

    print(f"Rules version {RULES_VERSION}\n")
    failed = 0
    for kind, rows in results.items():
        if kind == "synthetic" and real_only:
            continue
        passed = sum(1 for _, ok, _ in rows if ok)
        note = "" if kind == "real" else "   (plumbing check only - not an accuracy figure)"
        print(f"{kind.capitalize()} cases: {passed}/{len(rows)} correct{note}")
        for name, ok, problems in rows:
            print(
                f"  {'pass' if ok else 'FAIL'}  {name}"
                + ("" if ok else f"  - {'; '.join(problems)}")
            )
        if kind == "real" and not rows:
            print("  none yet - see docs/fault-testing.md for how to make them safely")
        failed += len(rows) - passed
        print()
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--real-only", action="store_true", help="skip the synthetic cases")
    sys.exit(run(parser.parse_args().real_only))
