"""Score the AI troubleshooter: does it name the right kind of cause?

    python eval/agent_eval.py              real labeled cases only
    python eval/agent_eval.py --synthetic  also the built-in samples (plumbing check)
    python eval/agent_eval.py --limit 5    stop after five cases (each case is one paid API call)

Needs ANTHROPIC_API_KEY (in the environment or .env) and
pip install -e "api[ai]". Every case costs one API call, so the script says
how many it is about to make and stops unless you pass --yes.

A real case is graded on the "cause_category" in its label.json (one of the
fault categories, e.g. "thermal"). Cases without that field are skipped. The
rules engine's own top category is printed next to it, so both can be
recorded in docs/results.md against the same cases.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from pcdoctor_analysis import analyze_run_dir, synth
from pcdoctor_api.config import get_settings
from pcdoctor_api.routers.assist import troubleshoot_material
from pcdoctor_api.services import ai

CASES = Path(__file__).parent / "cases"


def cases(with_synthetic: bool) -> list[tuple[str, str, Path | synth.SampleRun, str]]:
    found = []
    for label_file in sorted(CASES.glob("*/label.json")):
        label = json.loads(label_file.read_text())
        if label.get("cause_category"):
            found.append(("real", label_file.parent.name, label_file.parent, label["cause_category"]))
    if with_synthetic:
        for sample in synth.build_all():
            if sample.expected:
                found.append(("synthetic", sample.name, sample, sample.expected[0].split(".")[0]))
    return found


def grade(folder: Path, settings) -> tuple[str, str, dict]:
    result = analyze_run_dir(folder)
    material = troubleshoot_material(
        result.findings,
        result.device,
        [c.to_dict() for c in result.checks],
        result.frame_stats,
    )
    answer = ai.troubleshoot(settings, material, {f.code for f in result.findings})
    rules_top = result.findings[0].category if result.findings else "no_fault_found"
    return answer["category"], rules_top, answer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--synthetic", action="store_true", help="include the built-in samples")
    parser.add_argument("--limit", type=int, default=0, help="grade at most this many cases")
    parser.add_argument("--yes", action="store_true", help="do not ask before spending API calls")
    args = parser.parse_args()

    settings = get_settings()
    if not ai.available(settings):
        print("The AI helper is off: set ANTHROPIC_API_KEY and pip install -e 'api[ai]'.")
        return 2
    todo = cases(args.synthetic)
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("No cases with a cause_category yet - see docs/fault-testing.md.")
        return 0
    print(f"{len(todo)} case(s) = {len(todo)} API call(s) to {settings.ai_model}.")
    if not args.yes and input("Go ahead? [y/N] ").strip().lower() != "y":
        return 0

    score = {"real": [0, 0, 0], "synthetic": [0, 0, 0]}  # agent right, rules right, total
    for kind, name, source, expected in todo:
        try:
            if isinstance(source, Path):
                got, rules_top, answer = grade(source, settings)
            else:
                with tempfile.TemporaryDirectory() as folder:
                    source.write(folder)
                    got, rules_top, answer = grade(Path(folder), settings)
        except ai.AiError as error:
            print(f"  ERROR {name}: {error}")
            score[kind][2] += 1
            continue
        score[kind][0] += got == expected
        score[kind][1] += rules_top == expected
        score[kind][2] += 1
        mark = "pass" if got == expected else "FAIL"
        print(f"  {mark}  {name}: expected {expected}, agent {got} "
              f"({answer['confidence']}), rules {rules_top}")
    for kind, (agent, rules, total) in score.items():
        if total:
            note = "" if kind == "real" else "   (plumbing check only - not an accuracy figure)"
            print(f"{kind.capitalize()}: agent {agent}/{total}, rules engine {rules}/{total}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
