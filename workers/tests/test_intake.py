from __future__ import annotations

from pcdoctor_analysis.errortext import interpret
from pcdoctor_analysis.model import CATEGORIES
from pcdoctor_analysis.noboot import BY_KEY, SYMPTOMS

MODERN = """:(
Your PC ran into a problem and needs to restart. We're just
collecting some error info, and then we'll restart for you.
20% complete
Stop code: CRITICAL PROCESS DIED
"""


def codes(text: str) -> list[str]:
    return [entry.hex for entry in interpret(text).stop_codes]


def test_reads_a_stop_code_by_name_even_without_underscores():
    reading = interpret(MODERN)
    assert reading.is_blue_screen
    assert [e.name for e in reading.stop_codes] == ["CRITICAL_PROCESS_DIED"]
    assert codes("Stop code: VIDEO_TDR_FAILURE\nWhat failed: nvlddmkm.sys") == ["0x116"]
    assert interpret("Stop code: VIDEO_TDR_FAILURE\nWhat failed: nvlddmkm.sys").drivers == [
        "nvlddmkm.sys"
    ]


def test_reads_a_stop_code_by_number_and_forgives_ocr_zeroes():
    assert codes("*** STOP: 0x00000124 (0x0000000000000000, 0xFFFFE001)") == ["0x124"]
    assert codes("STOP: 0xOOOOOO7E") == ["0x7E"]  # letter O instead of zero
    assert codes("stop code 0x 0000001A") == ["0x1A"]


def test_tolerates_small_ocr_mistakes_in_the_name():
    assert codes("Stop code: CRITICAL PR0CESS DlED") == ["0xEF"]
    assert codes("Stop code: MEMORY MANAGEMEMT") == ["0x1A"]


def test_prefers_the_longest_matching_name():
    names = [e.name for e in interpret("SYSTEM_THREAD_EXCEPTION_NOT_HANDLED_M").stop_codes]
    assert names == ["SYSTEM_THREAD_EXCEPTION_NOT_HANDLED_M"]


def test_never_invents_a_code():
    for text in ("", "   ", "Press F1 to continue", "Total 0 items, 0x0"):
        reading = interpret(text)
        assert reading.stop_codes == [] and not reading.is_blue_screen
    unknown = interpret("Your PC ran into a problem. STOP: 0x000ABCDE")
    assert unknown.stop_codes == [] and unknown.unknown_codes == ["0xABCDE"]


def test_no_boot_guide_is_complete():
    assert len(SYMPTOMS) >= 10 and len(BY_KEY) == len(SYMPTOMS)
    for symptom in SYMPTOMS:
        assert symptom.category in CATEGORIES
        assert len(symptom.causes) >= 2 and len(symptom.checks) >= 3
        assert symptom.to_dict()["checks"][0]
    assert {"led_cpu", "led_dram", "led_vga", "led_boot", "no_power"} <= set(BY_KEY)
