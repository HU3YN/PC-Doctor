"""Fuzz the run loader and the analysis after it
(workers/pcdoctor_analysis/loader.py and analyze.py).

loader.py promises: "A missing or damaged file becomes a note, never a
crash". So for ANY bytes in the files of a run folder:

* load_run_dir returns RunData;
* analyze_run_dir returns an AnalysisResult that can be stored as JSON;
* no check inside the rules engine crashes. The engine catches a crashing
  check and reports "Check ... failed", so the run is not lost - but that
  check silently did not run, which for a diagnosis tool is a wrong answer.
"""

from __future__ import annotations

import known_bugs
import strategies
from harness import STRICT, check_result, rule_errors, sandbox, tolerate
from hypothesis import event, given
from hypothesis import strategies as st
from pcdoctor_analysis import analyze_run_dir, load_run_dir
from pcdoctor_analysis.loader import RunData


def check_run_folder(files: dict[str, bytes]) -> None:
    with sandbox() as box:
        for name, content in files.items():
            (box.dest / name).write_bytes(content)
        before = box.files()
        box.opened_for_writing.clear()
        try:
            run = load_run_dir(box.dest)
            assert isinstance(run, RunData)
            assert all(isinstance(note, str) for note in run.notes)
            result = analyze_run_dir(box.dest)
            check_result(result)
        except Exception as error:  # noqa: BLE001 - "never a crash"
            tolerate(error)
            return
        # Reading a run must not write anything, anywhere.
        assert box.opened_for_writing == [], box.opened_for_writing
        assert box.files() == before
        for note in rule_errors(result):
            bug = None if STRICT else known_bugs.match_note(note)
            assert bug is not None, f"a check crashed: {note}"
            event(f"known bug {bug.id}")


json_files = st.fixed_dictionaries(
    {},
    optional={name: strategies.json_file(name) for name in strategies.JSON_FILES},
)


@given(json_files)
def test_loader_with_hostile_json(files: dict[str, bytes]) -> None:
    check_run_folder(files)


@given(
    json_files,
    st.one_of(st.none(), strategies.presentmon_text()),
    st.one_of(st.none(), strategies.sensors_text()),
)
def test_loader_with_hostile_json_and_csv(
    files: dict[str, bytes], presentmon: str | None, sensors: str | None
) -> None:
    files = dict(files)
    if presentmon is not None:
        files["presentmon.csv"] = presentmon.encode("utf-8", errors="replace")
    if sensors is not None:
        files["sensors.csv"] = sensors.encode("utf-8", errors="replace")
    check_run_folder(files)


@given(
    st.dictionaries(
        st.sampled_from(sorted(strategies.RUN_FILES)), st.binary(max_size=300)
    )
)
def test_loader_with_random_bytes(files: dict[str, bytes]) -> None:
    check_run_folder(files)
