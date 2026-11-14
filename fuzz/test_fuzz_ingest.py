"""Fuzz the upload unpacker (api/pcdoctor_api/services/ingest.py, unpack).

Anyone with a guest or bot upload link can send any bytes, and unpack is the
first code that reads them. Its contract, from its module docstring:

* it raises UploadError (a message safe to show) or returns - nothing else;
* nothing is written outside the destination folder, and nothing in the
  archive can choose where a file lands;
* only the allow-listed run file names appear in the destination, and the
  names it returns are exactly the files it wrote;
* the bytes written never pass ``max_unpacked_mb``, whatever the zip claims.

The limit is set to 1 MB here (the smallest the settings allow) so that a
zip bomb only a few kilobytes long is enough to cross it.
"""

from __future__ import annotations

import strategies
from harness import sandbox, tolerate
from hypothesis import given
from hypothesis import strategies as st
from pcdoctor_api.config import Settings
from pcdoctor_api.services.ingest import MAX_ARCHIVE_ENTRIES, UploadError, unpack
from strategies import BOMB, RUN_FILES, Entry, raw_zip

SETTINGS = Settings(max_unpacked_mb=1)
LIMIT = SETTINGS.max_unpacked_mb * 1024 * 1024


def check_unpack(data: bytes) -> list[str] | None:
    """Unpack ``data`` in a sandbox and check every promise. Returns the names
    unpack returned, or None when it refused the upload."""
    with sandbox() as box:
        names: list[str] | None = None
        try:
            names = unpack(data, box.dest, SETTINGS)
        except UploadError as error:
            assert str(error), "an UploadError must say what is wrong"
        except Exception as error:  # noqa: BLE001 - any other type is a finding
            tolerate(error)
            return None
        # Nothing written outside dest: neither opened for writing...
        assert box.writes_outside() == [], box.writes_outside()
        # ...nor present afterwards (cwd is where a relative name would land).
        files = box.files()
        outside = [path for path in files if not path.startswith("dest/")]
        assert outside == [], outside
        # No folders inside dest: the archive cannot choose a path.
        assert box.folders() <= {"dest", "cwd"}, box.folders()
        written = {path.removeprefix("dest/"): size for path, size in files.items()}
        assert set(written) <= RUN_FILES, sorted(written)
        assert sum(written.values()) <= LIMIT, sum(written.values())
        if names is not None:
            assert names == sorted(written), (names, sorted(written))
            assert names, "success with no files"
        return names


# ------------------------------------------------------------ broad inputs


@given(st.binary(max_size=2000))
def test_unpack_random_bytes(data: bytes) -> None:
    check_unpack(data)


@given(st.binary(max_size=2000))
def test_unpack_random_bytes_after_zip_magic(tail: bytes) -> None:
    check_unpack(b"PK\x03\x04" + tail)


@given(strategies.upload_bytes())
def test_unpack_hostile_uploads(data: bytes) -> None:
    check_unpack(data)


# ---------------------------------------------------------- targeted attacks

ATTACK_PREFIXES = st.sampled_from(
    [
        b"../",
        b"../../../../",
        b"..\\..\\",
        b"/",
        b"/etc/",
        b"/tmp/",
        b"C:\\",
        b"C:/Windows/",
        b"\\\\server\\share\\",
        b"run/../../",
        b"run\\..\\",
        b"./../",
        b"a/b/",
    ]
)
KNOWN_NAME = st.sampled_from(sorted(RUN_FILES)).map(str.encode)


@given(ATTACK_PREFIXES, KNOWN_NAME, st.binary(max_size=200))
def test_unpack_path_traversal_and_absolute_names(
    prefix: bytes, name: bytes, data: bytes
) -> None:
    # Path traversal (../x), absolute paths, drive letters and backslashes.
    check_unpack(raw_zip([Entry(name=prefix + name, data=data)]))


@given(
    st.lists(
        st.tuples(KNOWN_NAME, st.sampled_from([b"", b"run/", b"RUN\\"])), min_size=2
    ),
    st.binary(max_size=100),
    st.booleans(),
)
def test_unpack_duplicate_names(
    picks: list[tuple[bytes, bytes]], data: bytes, upper: bool
) -> None:
    entries = []
    for i, (name, prefix) in enumerate(picks + picks):  # every name at least twice
        entries.append(
            Entry(name=prefix + (name.upper() if upper and i % 2 else name), data=data)
        )
    names = check_unpack(raw_zip(entries))
    if names is not None:
        assert len(names) == len(set(names))


@given(st.integers(MAX_ARCHIVE_ENTRIES + 1, MAX_ARCHIVE_ENTRIES + 60), KNOWN_NAME)
def test_unpack_refuses_too_many_entries(total: int, name: bytes) -> None:
    entries = [Entry(name=name, data=b"{}")]
    entries += [
        Entry(name=b"filler-%d.txt" % i, data=b"x", method=0) for i in range(total - 1)
    ]
    assert check_unpack(raw_zip(entries)) is None


@given(
    KNOWN_NAME,
    st.sampled_from([None, 0, 1, 1000, LIMIT - 1, LIMIT, LIMIT + 1]),
    st.integers(0, 3),
)
def test_unpack_zip_bomb_against_small_limit(
    name: bytes, declared: int | None, extra: int
) -> None:
    # BOMB is 2 MB of zeros: a few kilobytes compressed, twice the limit
    # unpacked. A lying declared size must not get it past the limit.
    entries = [Entry(name=name, data=BOMB, declared_size=declared)]
    entries += [
        Entry(name=n.encode(), data=b"\x00" * 300_000)
        for n in sorted(RUN_FILES)[:extra]
    ]
    assert check_unpack(raw_zip(entries)) is None


@given(
    KNOWN_NAME, st.sampled_from([0x1, 0x41, 0x2001, 0xFFFF]), st.binary(max_size=200)
)
def test_unpack_refuses_encrypted_entries(name: bytes, flags: int, data: bytes) -> None:
    assert check_unpack(raw_zip([Entry(name=name, data=data, flags=flags)])) is None


@given(st.binary(max_size=100), st.integers(1, 1000))
def test_unpack_bare_csv_respects_the_limit(tail: bytes, over: int) -> None:
    # A bare PresentMon .csv bigger than the limit.
    data = b"Application,MsBetweenPresents\n" + tail
    data += b"1\n" * ((LIMIT + over - len(data)) // 2 + 1)
    assert len(data) > LIMIT
    assert check_unpack(data) is None
