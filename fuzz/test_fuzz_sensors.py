"""Fuzz the sensors CSV parser (workers/pcdoctor_analysis/sensors.py).

The contract, from loader.py: parse_sensors_csv returns SensorData or raises
OSError / ValueError (the loader turns those into a note). After that:

* every column has exactly one value per sample;
* every kept reading is inside its valid range (so it is finite);
* the summary and the chart series are finite numbers.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from pcdoctor_analysis.sensors import (
    SENSOR_COLUMNS,
    VALID_RANGES,
    SensorData,
    parse_sensors_csv,
    summarize,
)
from pcdoctor_analysis.series import sensor_series

import strategies
from harness import tolerate


def check_sensors(raw: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="pcdoctor-fuzz-") as temp:
        path = Path(temp) / "sensors.csv"
        path.write_bytes(raw)
        try:
            data = parse_sensors_csv(path)
        except (OSError, ValueError):
            return  # what loader.py is written to expect
        except Exception as error:  # noqa: BLE001 - any other type is a finding
            tolerate(error)
            return
    assert isinstance(data, SensorData)
    try:
        for column, values in data.series.items():
            assert column in SENSOR_COLUMNS
            assert len(values) == data.samples, (
                f"{column} has {len(values)} values for {data.samples} samples"
            )
            low, high = VALID_RANGES[column]
            assert all(v is None or low <= v <= high for v in values)
        assert all(math.isfinite(t) for t in data.elapsed_s), "elapsed_s holds inf"
        json.dumps([summarize(data), sensor_series(data)], allow_nan=False)
    except Exception as error:  # noqa: BLE001
        tolerate(error)


@given(strategies.sensors_text())
def test_sensors_parser(text: str) -> None:
    check_sensors(text.encode("utf-8", errors="replace"))


@given(st.binary(max_size=600))
def test_sensors_parser_random_bytes(raw: bytes) -> None:
    check_sensors(raw)
