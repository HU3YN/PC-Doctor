# fuzz

Property-based fuzz tests (Python, [Hypothesis](https://hypothesis.readthedocs.io))
for the code that reads files from strangers, plus one Go fuzz target in
`upload-service/`. **Fuzz only this project's own code, on your own machines.**
Nothing here talks to the network or to a service someone else runs.

## What is fuzzed

| Test file | Code under test | What must always hold |
|---|---|---|
| `test_fuzz_ingest.py` | `api/pcdoctor_api/services/ingest.py`, `unpack` | Only `UploadError` is raised; nothing is written outside the destination folder (an audit hook records every file opened for writing); only the allow-listed run file names appear, with no folders; the bytes written never pass `max_unpacked_mb` (set to 1 MB). Inputs: random bytes, random bytes after a zip signature, hand-built hostile zips (`../` and `..\` traversal, absolute and drive-letter paths, backslashes, duplicate and case-duplicate names, 201+ entries, a 2 MB zip bomb with a lying declared size, the encrypted flag bit, unsupported compression methods, bad CRCs, names that are not UTF-8), and a bare CSV over the limit |
| `test_fuzz_loader.py` | `workers/pcdoctor_analysis/loader.py` and `analyze.py` | A run folder with any bytes in any file loads and analyses without an exception, no check inside the rules engine crashes, the result can be stored as JSON (no NaN or inf), and reading writes nothing |
| `test_fuzz_presentmon.py` | `workers/pcdoctor_analysis/presentmon.py` | Returns `FrameData` or raises `PresentMonError`; frame times positive and finite; stats and chart series finite |
| `test_fuzz_sensors.py` | `workers/pcdoctor_analysis/sensors.py` | Returns `SensorData` or raises `OSError`/`ValueError`; one value per sample in every column; readings in range; summary finite |
| `test_fuzz_errortext.py` | `workers/pcdoctor_analysis/errortext.py`, `interpret` | Never raises, never invents a stop code or driver that is not in the text, stays fast on long repetitive text |
| `upload-service/archive_test.go`, `FuzzCleanRun` | `upload-service/archive.go`, `CleanRun` | Never panics, never emits a file name outside the known list, never accepts an upload with no files |

`strategies.py` builds the inputs (valid sample runs from
`workers/pcdoctor_analysis/synth.py`, broken a little; zips built byte by
byte so every field can lie). `harness.py` has the write-recording sandbox and
the checks every analysis result must pass.

## Running

From the repository root, with the venv active (`hypothesis` installed):

```sh
# Short run (the default "ci" profile: 100 inputs per property, about 10 s here)
pytest -c fuzz/pytest.ini fuzz

# Long run ("long" profile: 5,000 inputs per property, about 6 minutes here)
PCDOCTOR_FUZZ_PROFILE=long pytest -c fuzz/pytest.ini fuzz --hypothesis-show-statistics

# Any number of inputs per property
PCDOCTOR_FUZZ_EXAMPLES=20000 pytest -c fuzz/pytest.ini fuzz

# Go: fuzz the upload service's zip cleaner for 60 seconds
cd upload-service && go test -run xxx -fuzz=FuzzCleanRun -fuzztime=60s .
```

`--hypothesis-show-statistics` prints, per test, how many inputs ran
("N passing, M failing, and K invalid test cases"); that is where the counts
in the table below come from.

## When a test finds a crash

1. Hypothesis shrinks the input and prints it, plus a
   `@reproduce_failure(...)` line. It also saves it in `.hypothesis/` (git
   ignored), so the next run tries it first. Go saves the input under
   `upload-service/testdata/fuzz/FuzzCleanRun/`; keep that file, it becomes a
   permanent seed.
2. Write the smallest input as a normal regression test: `workers/tests/test_fuzz_regressions.py`
   for the parsers and rules, `api/tests/test_ingest_regressions.py` for
   `unpack`. Check that it fails before the fix.
3. Fix the code under test, not the property. Run the regression test, the
   unit tests, and the fuzz tests again.
4. If a bug cannot be fixed now, list it in `known_bugs.py` (type and message
   piece) so the fuzz tests keep looking for the *next* bug, and run with
   `PCDOCTOR_FUZZ_STRICT=1` to see it again. The list is empty today.
5. Add a row to the table below.

## Results

Measured on 2026-11-14 in the cloud build container (4 CPUs, Python 3.13,
Hypothesis 6.170.15, Go 1.24.7). "Inputs run" is passing plus failing test
cases from Hypothesis' statistics (invalid, filtered-out cases not counted),
or `execs` from the Go fuzzer.

| Run | Inputs run | Time | Crashes / wrong results found | Fixed |
|---|---|---|---|---|
| Short runs while writing the tests (default 100-200 per property) | not counted | under 1 min each | 9 (bugs 1-9 below) | 9 |
| Python, `long` profile, run 1 | 80,485 | 6 min 11 s | 1 new (bug 10) | 1 |
| Python, `long` profile, run 2 (after all fixes) | 80,704 | 5 min 34 s | 0 | - |
| Go, `FuzzCleanRun`, 60 s | 1,115,863 | 61 s | 0 | - |

The bugs, each with a regression test (`W` = `workers/tests/test_fuzz_regressions.py`,
`A` = `api/tests/test_ingest_regressions.py`):

1. `presentmon.py`: a field over the csv module's 131,072-character limit
   raised `_csv.Error`, which the loader did not catch, so the upload failed
   with a server error. Now a `PresentMonError`. (W)
2. `sensors.py`: the same for `sensors.csv`. Now a `ValueError`, which the
   loader turns into a note. (W)
3. `sensors.py`: `inf` was accepted as a number, so `elapsed_s` held
   infinity and the result could not be stored as JSON. (W)
4. `sensors.py`: a column named twice got two values per sample. (W)
5. `rules/storage.py` and `rules/system.py`, `_number`: a 400-digit integer
   in `disks.json` raised `OverflowError` (the "Drive temperature" check
   crashed), and `"1e999"`/`"nan"` became inf/NaN in the result. (W)
6. `loader.py`: an event `id` that is a list or object made the WHEA and
   storage checks crash (`unhashable type`). Non-integer ids are now `None`. (W)
7. `ingest.unpack`: a zip entry name that is not valid UTF-8 but flagged as
   UTF-8 raised `UnicodeDecodeError` (a 500, not a 400). (A)
8. `ingest.unpack`: damaged entries raised `BadZipFile` (bad CRC) while
   reading; the same path also let `NotImplementedError` (unsupported
   compression) and `zlib.error`/`OSError` (corrupt data) out.
   All are now `UploadError`, and the encrypted-entry check runs before any
   file is written. (A)
9. `ingest.unpack`: a bare PresentMon `.csv` was written whatever its size,
   ignoring `max_unpacked_mb`. (A)
10. `presentmon.py`: a frame time of `5e-324` (1000 / it is inf) or `1e308`
    (two of them sum to inf) put infinity into the frame statistics. Frame
    times outside 0.001 ms - 1 hour are now skipped. (W)
