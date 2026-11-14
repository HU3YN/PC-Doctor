"""Input generators shared by the fuzz tests.

Everything here builds *hostile* versions of the files PC Doctor accepts from
strangers: run zips, PresentMon and sensor CSV files, the JSON files in a run
folder, and text read off a photo.

Two ideas do most of the work:

* Start from a valid file (made by workers/pcdoctor_analysis/synth.py) and
  break it a little. A file that is 95% right gets much deeper into the code
  than random bytes, which are rejected at the first check.
* Build zip files by hand, byte by byte, so that every field an attacker
  controls (name, flags, declared size, checksum, compression method) can be
  set to a lie. Python's own zipfile module refuses to write most lies.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from functools import cache, lru_cache
from typing import Any

from hypothesis import strategies as st
from pcdoctor_analysis import synth

# The same allow-list as api/pcdoctor_api/services/ingest.py. Kept as its own
# copy on purpose: if someone widens the list in the code by accident, the
# fuzz tests still check against what the documentation promises
# (docs/privacy.md, "What is uploaded").
RUN_FILES = frozenset(
    {
        "manifest.json",
        "specs.json",
        "events.json",
        "disks.json",
        "presentmon.csv",
        "sensors.csv",
        "sensors_raw.json",
        "collector.log",
    }
)
JSON_FILES = ("manifest.json", "specs.json", "events.json", "disks.json")


# --------------------------------------------------------------- seed corpus


@lru_cache(maxsize=1)
def seed_runs() -> tuple[dict[str, str], ...]:
    """The files of every synthetic sample run. Made-up data, no real PC."""
    return tuple(dict(sample.files) for sample in synth.build_all())


@lru_cache(maxsize=1)
def seed_documents() -> dict[str, tuple[Any, ...]]:
    """Every seed JSON file, parsed, grouped by file name."""
    out: dict[str, list[Any]] = {name: [] for name in JSON_FILES}
    for files in seed_runs():
        for name in JSON_FILES:
            if name in files:
                out[name].append(json.loads(files[name]))
    return {name: tuple(docs) for name, docs in out.items()}


@cache
def seed_csv(name: str) -> tuple[str, ...]:
    """The first lines of every seed CSV of one kind (short, so tests stay fast)."""
    found = []
    for files in seed_runs():
        if name in files:
            found.append("".join(files[name].splitlines(keepends=True)[:40]))
    return tuple(found)


# --------------------------------------------------------------------- JSON

# Values that tend to break code which expected "a number" or "a short string".
HOSTILE_SCALARS: tuple[Any, ...] = (
    None,
    True,
    False,
    0,
    -1,
    1,
    2**31,
    2**63,
    2**70,
    -(2**70),
    10**400,  # too big for a float
    0.0,
    -0.0,
    1e308,
    -1e308,
    5e-324,
    1e-320,
    0.1,
    "",
    " ",
    "0",
    "-1",
    "1e999",
    "NaN",
    "null",
    "\x00",
    "a\x00b",
    "\ud800",  # half of a surrogate pair: cannot be encoded as UTF-8
    "\u202e",  # right-to-left override
    "x" * 5000,
    "<script>alert(1)</script>",
    "../../etc/passwd",
    "2026-13-45T99:99:99Z",
    "0001-01-01T00:00:00+23:59",
    "9999-12-31T23:59:59-23:59",
    "0xFFFFFFFFFFFFFFFFFFFF",
    "%s%s%s%n",
    "${jndi:ldap://x}",
)

hostile_scalar = st.one_of(
    st.sampled_from(HOSTILE_SCALARS),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=40),
)

json_value = st.recursive(
    hostile_scalar,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=12), children, max_size=5),
    ),
    max_leaves=25,
)


def _paths(value: Any, prefix: tuple = ()) -> list[tuple]:
    """Every position inside a JSON document, as a path of keys and indexes."""
    found = [prefix]
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_paths(child, (*prefix, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value[:8]):  # the first few items are enough
            found.extend(_paths(child, (*prefix, index)))
    return found


def _replace(value: Any, path: tuple, new: Any) -> Any:
    """A copy of ``value`` with the item at ``path`` replaced by ``new``."""
    if not path:
        return new
    head, rest = path[0], path[1:]
    if isinstance(value, dict):
        return {
            k: (_replace(v, rest, new) if k == head else v) for k, v in value.items()
        }
    return [(_replace(v, rest, new) if i == head else v) for i, v in enumerate(value)]


@st.composite
def mutated_document(draw: st.DrawFn, name: str) -> Any:
    """A seed JSON document with a few values swapped for hostile ones."""
    document = draw(st.sampled_from(seed_documents()[name]))
    for _ in range(draw(st.integers(1, 6))):
        paths = _paths(document)
        path = draw(st.sampled_from(paths))
        document = _replace(document, path, draw(st.one_of(hostile_scalar, json_value)))
    return document


def dump_json(value: Any) -> bytes:
    """JSON text as bytes. Half-surrogates are kept as \\udXXX escapes."""
    return json.dumps(value).encode("utf-8")


# Text that is "almost JSON": the parser must turn every one of these into a
# note, never into a crash.
BROKEN_JSON: tuple[bytes, ...] = (
    b"",
    b"{",
    b"[" * 100_000,  # far deeper than Python's recursion limit
    b'{"a":' * 50_000,
    b'{"a": ' + b"9" * 5000 + b"}",  # more digits than Python converts by default
    b"-" + b"9" * 5000,
    b"NaN",
    b"Infinity",
    b'{"a": NaN, "b": -Infinity}',
    b"\xff\xfe{\x00}\x00",  # UTF-16
    b"\xef\xbb\xbf{}",  # byte-order mark, as PowerShell 5.1 writes
    b'{"a": "\\ud800"}',
    b'{"a": 1}{"b": 2}',
    b"1e999999",
    b'"just a string"',
    b"[1, 2, 3]",
    b"null",
)


def json_file(name: str) -> st.SearchStrategy[bytes]:
    """Bytes for one JSON file of a run: mutated seed, random JSON, or junk."""
    return st.one_of(
        mutated_document(name).map(dump_json),
        mutated_document(name).map(dump_json),  # listed twice: the most useful kind
        json_value.map(dump_json),
        st.sampled_from(BROKEN_JSON),
        st.binary(max_size=200),
    )


# ---------------------------------------------------------------------- CSV

# Cells a number parser has to survive.
HOSTILE_CELLS: tuple[str, ...] = (
    "",
    " ",
    "NA",
    "na",
    "NaN",
    "nan",
    "inf",
    "-inf",
    "Infinity",
    "1e308",
    "1e309",
    "-1e308",
    "5e-324",
    "1e-320",
    "0",
    "-0",
    "-1",
    "0.0",
    "16.6",
    "16,6",  # decimal comma, as some Windows locales write
    "1_000",
    "0x10",
    "１６",  # full-width digits: float() accepts these
    "١٦",  # Arabic-Indic digits: float() accepts these too
    "1" * 400,
    "\x00",
    "1\x00",
    '"',
    '""',
    "a,b",
    "\r",
    "game.exe",
    "dwm.exe",
    "=cmd|' /C calc'!A0",  # spreadsheet formula injection
)

cell = st.one_of(
    st.sampled_from(HOSTILE_CELLS),
    st.floats(allow_nan=False, allow_infinity=False, width=32).map(
        lambda f: f"{f:.4f}"
    ),
    st.floats().map(repr),
    st.integers(-5, 200).map(str),
    st.text(max_size=12),
)

PRESENTMON_COLUMNS = (
    *synth.PRESENTMON_HEADER,
    "FrameTime",
    "msBetweenPresents",
    "CPUStartTime",
    "TimeInMs",
    "GPUBusy",
    "msGPUActive",
    "CPUBusy",
    "DisplayedTime",
    "Dropped",
    "application",
    " MsBetweenPresents ",
    "",
)
SENSOR_COLUMNS = (
    "elapsed_s",
    "cpu_temp_c",
    "cpu_load_pct",
    "cpu_core_max_load_pct",
    "cpu_clock_mhz",
    "cpu_perf_pct",
    "cpu_power_w",
    "gpu_temp_c",
    "gpu_hotspot_c",
    "gpu_load_pct",
    "gpu_clock_mhz",
    "gpu_power_w",
    "gpu_fan_rpm",
    "gpu_vram_used_pct",
    "ram_used_pct",
    " cpu_temp_c",
    "CPU_TEMP_C",
    "",
    "unknown_column",
)


@st.composite
def csv_table(
    draw: st.DrawFn, columns: tuple[str, ...], must_have: tuple[str, ...]
) -> str:
    """A table with a plausible header and hostile cells.

    Rows may be shorter or longer than the header, and a column name may be
    repeated - both happen in damaged files.
    """
    header = list(draw(st.lists(st.sampled_from(columns), min_size=0, max_size=10)))
    if draw(st.booleans()):
        header.insert(
            draw(st.integers(0, len(header))), draw(st.sampled_from(must_have))
        )
    separator = draw(st.sampled_from([",", ",", ",", ";", "\t"]))
    newline = draw(st.sampled_from(["\n", "\r\n", "\r", "\n\n"]))
    width = st.integers(max(0, len(header) - 2), len(header) + 2)
    rows = draw(
        st.lists(
            st.lists(cell, min_size=0, max_size=12).flatmap(_fit(width)), max_size=40
        )
    )
    lines = [separator.join(header)] + [separator.join(row) for row in rows]
    return draw(st.sampled_from(["", "\ufeff"])) + newline.join(lines) + newline


def _fit(width: st.SearchStrategy[int]):
    """Cut or pad a row to a drawn width (so most rows roughly fit the header)."""

    def fit(row: list[str]) -> st.SearchStrategy[list[str]]:
        return width.map(lambda n: (row + ["1"] * n)[:n])

    return fit


@st.composite
def mutated_csv(draw: st.DrawFn, name: str) -> str:
    """A seed CSV with a handful of cells swapped for hostile ones."""
    lines = draw(st.sampled_from(seed_csv(name))).splitlines()
    table = [line.split(",") for line in lines]
    for _ in range(draw(st.integers(1, 12))):
        row = draw(st.integers(0, len(table) - 1))
        if not table[row]:
            continue
        column = draw(st.integers(0, len(table[row]) - 1))
        table[row][column] = draw(cell)
    return "\n".join(",".join(row) for row in table) + "\n"


# A quoted field longer than the csv module's 131072-character field limit.
OVERSIZE_FIELD = '"' + "a" * 140_000 + '"'


def presentmon_text() -> st.SearchStrategy[str]:
    return st.one_of(
        csv_table(PRESENTMON_COLUMNS, ("MsBetweenPresents", "FrameTime")),
        mutated_csv("presentmon.csv"),
        st.just("MsBetweenPresents\n" + OVERSIZE_FIELD + "\n"),
        st.text(max_size=300),
    )


def sensors_text() -> st.SearchStrategy[str]:
    return st.one_of(
        csv_table(SENSOR_COLUMNS, ("elapsed_s", "cpu_temp_c", "gpu_temp_c")),
        mutated_csv("sensors.csv"),
        st.just("elapsed_s,cpu_temp_c\n" + OVERSIZE_FIELD + ",50\n"),
        st.text(max_size=300),
    )


# --------------------------------------------------------------------- zips


@dataclass
class Entry:
    """One file inside a hand-built zip. Every field can be a lie."""

    name: bytes
    data: bytes = b""
    method: int = 8  # 0 = stored, 8 = deflate; anything else is "unsupported"
    flags: int = 0  # bit 0 = encrypted, bit 11 = name is UTF-8
    declared_size: int | None = None  # None = tell the truth
    crc: int | None = None  # None = tell the truth
    local_name: bytes | None = None  # name in the local header, if different
    corrupt_body: bool = False  # damage the compressed bytes


def raw_zip(entries: list[Entry], declared_count: int | None = None) -> bytes:
    """Build a zip from ``entries`` exactly as described, lies included."""
    body = bytearray()
    central = bytearray()
    for entry in entries:
        if entry.method == 8:
            packer = zlib.compressobj(9, zlib.DEFLATED, -15)
            packed = packer.compress(entry.data) + packer.flush()
        else:
            packed = entry.data
        if entry.corrupt_body and packed:
            packed = bytes([packed[0] ^ 0xFF]) + packed[1:]
        crc = zlib.crc32(entry.data) if entry.crc is None else entry.crc
        size = len(entry.data) if entry.declared_size is None else entry.declared_size
        size &= 0xFFFFFFFF
        offset = len(body)
        local_name = entry.name if entry.local_name is None else entry.local_name
        body += struct.pack(
            "<4sHHHHHIIIHH",
            b"PK\x03\x04",
            20,
            entry.flags & 0xFFFF,
            entry.method & 0xFFFF,
            0,
            0x21,
            crc & 0xFFFFFFFF,
            len(packed),
            size,
            len(local_name),
            0,
        )
        body += local_name + packed
        central += struct.pack(
            "<4sHHHHHHIIIHHHHHII",
            b"PK\x01\x02",
            20,
            20,
            entry.flags & 0xFFFF,
            entry.method & 0xFFFF,
            0,
            0x21,
            crc & 0xFFFFFFFF,
            len(packed),
            size,
            len(entry.name),
            0,
            0,
            0,
            0,
            0,
            offset,
        )
        central += entry.name
    count = len(entries) if declared_count is None else declared_count
    end = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06",
        0,
        0,
        count & 0xFFFF,
        count & 0xFFFF,
        len(central),
        len(body),
        0,
    )
    return bytes(body) + bytes(central) + end


# Where an attacker would like a file to land.
NAME_PREFIXES: tuple[bytes, ...] = (
    b"",
    b"",
    b"",
    b"run/",
    b"PCDoctor-run-20261101/",
    b"run\\",
    b"./",
    b"../",
    b"../../",
    b"..\\..\\",
    b"/",
    b"//",
    b"/etc/",
    b"/tmp/",
    b"C:\\",
    b"C:/Windows/",
    b"\\\\server\\share\\",
    b"a/b/",
    b"a/b/c/d/",
    b"a/../",
    b"run//",
    b"run/./",
    b"~/",
    b"\xff\xfe/",  # not valid UTF-8
    b"\xc3\x28/",  # not valid UTF-8
    b"nul/",
    b"con/",
    b" /",
)
OTHER_NAMES: tuple[bytes, ...] = (
    b"evil.exe",
    b"manifest.json.exe",
    b"manifest.json/",
    b"manifest.json\x00.txt",
    b"manifest.json ",
    b"manifest.json.",
    b"manifest.json::$DATA",
    b"..",
    b".",
    b"",
    b"/",
    b".env",
    b"setup-code.txt",
    b"pcdoctor.sqlite3",
    b"\xff\xff\xff",
    b"MANIFEST.JSON",
    b"Specs.Json",
    b"a" * 300,
    b"index.html",
)

known_name = st.sampled_from(sorted(RUN_FILES)).map(str.encode)
entry_name = st.builds(
    lambda prefix, name, upper: prefix + (name.upper() if upper else name),
    st.sampled_from(NAME_PREFIXES),
    st.one_of(
        known_name, known_name, st.sampled_from(OTHER_NAMES), st.binary(max_size=20)
    ),
    st.booleans(),
)

# Compresses to a few kilobytes, unpacks to more than the 1 MB test limit.
BOMB = b"\x00" * (2 * 1024 * 1024)


def _seed_file_bytes() -> st.SearchStrategy[bytes]:
    files = [content.encode("utf-8") for run in seed_runs() for content in run.values()]
    return st.sampled_from(files)


entry_data = st.one_of(
    st.binary(max_size=64),
    st.binary(max_size=64),
    _seed_file_bytes(),
    st.sampled_from(BROKEN_JSON),
    st.just(BOMB),
    st.sampled_from([b"\x00" * 600_000, b"A" * 600_000]),  # two of these pass 1 MB
)


@st.composite
def entry(draw: st.DrawFn) -> Entry:
    data = draw(entry_data)
    return Entry(
        name=draw(entry_name),
        data=data,
        method=draw(st.sampled_from([8, 8, 8, 0, 0, 12, 14, 93, 99, 1, 65535])),
        flags=draw(
            st.sampled_from([0, 0, 0, 0, 0x800, 0x1, 0x8, 0x41, 0x2000, 0xFFFF])
        ),
        declared_size=draw(
            st.sampled_from([None, None, None, 0, 1, len(data) + 1, 0xFFFFFFFF, 2**31])
        ),
        crc=draw(st.sampled_from([None, None, None, 0, 0xDEADBEEF])),
        local_name=draw(st.sampled_from([None, None, None, b"other.txt", b"../../x"])),
        corrupt_body=draw(st.sampled_from([False, False, False, True])),
    )


@st.composite
def honest_entry(draw: st.DrawFn) -> Entry:
    """An entry with a hostile name and content, but a well-formed zip record."""
    return Entry(
        name=draw(entry_name),
        data=draw(entry_data),
        method=draw(st.sampled_from([8, 0])),
    )


@st.composite
def hostile_zip(draw: st.DrawFn) -> bytes:
    """A structured zip built to attack the unpacker."""
    kind = draw(st.sampled_from(["honest", "honest", "lying", "many", "damaged"]))
    if kind == "honest":
        entries = draw(st.lists(honest_entry(), min_size=0, max_size=12))
        return raw_zip(entries)
    if kind == "lying":
        entries = draw(st.lists(entry(), min_size=1, max_size=8))
        count = draw(st.sampled_from([None, None, 0, 1, 65535]))
        return raw_zip(entries, declared_count=count)
    if kind == "many":
        # Around the 200-entry limit, with a few real run files among them.
        total = draw(st.integers(195, 230))
        real = draw(st.lists(honest_entry(), min_size=0, max_size=4))
        filler = [
            Entry(name=b"filler-%d.txt" % i, data=b"x", method=0) for i in range(total)
        ]
        return raw_zip(filler[: max(0, total - len(real))] + real)
    # "damaged": a good zip with bytes flipped, cut off, or glued together.
    good = bytearray(raw_zip(draw(st.lists(honest_entry(), min_size=1, max_size=4))))
    for _ in range(draw(st.integers(1, 8))):
        position = draw(st.integers(0, len(good) - 1))
        good[position] = draw(st.integers(0, 255))
    if draw(st.booleans()):
        good = good[: draw(st.integers(4, len(good)))]
    return bytes(good)


def upload_bytes() -> st.SearchStrategy[bytes]:
    """Anything a stranger might send as "a run"."""
    return st.one_of(
        hostile_zip(),
        hostile_zip(),
        hostile_zip(),
        st.binary(max_size=400),
        st.binary(max_size=400).map(lambda tail: b"PK\x03\x04" + tail),
        st.binary(max_size=400).map(lambda tail: b"PK\x05\x06" + tail),
        presentmon_text().map(lambda text: text.encode("utf-8", errors="replace")),
    )


@st.composite
def run_zip(draw: st.DrawFn) -> bytes:
    """A well-formed zip of a run whose *contents* are hostile.

    The unpacker accepts these, so they test the step after it: analysis.
    """
    files: dict[str, bytes] = {}
    for name in JSON_FILES:
        if draw(st.booleans()):
            files[name] = draw(json_file(name))
    if draw(st.booleans()):
        files["presentmon.csv"] = draw(presentmon_text()).encode(
            "utf-8", errors="replace"
        )
    if draw(st.booleans()):
        files["sensors.csv"] = draw(sensors_text()).encode("utf-8", errors="replace")
    if not files:
        files["manifest.json"] = draw(json_file("manifest.json"))
    return raw_zip(
        [Entry(name=name.encode(), data=data) for name, data in files.items()]
    )
