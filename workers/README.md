# pcdoctor-analysis

Reads a run folder written by the PC Doctor collector and works out what is
wrong with the PC. Standard library only, so it runs anywhere Python 3.11+ does.

```bash
pip install -e ".[dev]"

pcdoctor-analyze path/to/PCDoctor-run-20261101-180000     # full diagnosis
pcdoctor-analyze path/to/run --json                       # the same, as JSON
pcdoctor-analyze frames path/to/presentmon.csv            # average FPS, 1% low, spikes
pcdoctor-analyze rules                                    # every fault type it detects

pytest          # tests
ruff check .    # lint
```

| Module | What it does |
|---|---|
| `loader.py` | Reads the run folder; a missing or damaged file becomes a note, not a crash |
| `presentmon.py` | Parses PresentMon CSVs (every header style) and computes frame statistics |
| `sensors.py` | Parses the collector's `sensors.csv` |
| `rules/` | One small function per fault type; `rules/__init__.py` runs them all |
| `stopcodes.py` | Blue-screen stop codes: meaning, usual causes, first checks |
| `analyze.py` | Puts it together into the result the API stores |
| `synth.py` | Synthetic sample runs for tests and the demo (never real measurements) |

Thresholds live in one place: `Thresholds` in `model.py`. See `docs/rules.md`.
