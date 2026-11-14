#!/usr/bin/env bash
# Build pcdoctor-capture, make a run zip from the test fixtures, and check
# that the Python analyzer reads it - the same check the CI collector job runs
# on the PowerShell collector's output (no "could not be read / is missing /
# does not know" notes).
#
#   collector-rs/scripts/check-with-analyzer.sh [path/to/pcdoctor-analyze]
#
# Default analyzer: the repository's .venv (pip install -e workers).
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
repo="$(cd "$here/.." && pwd)"
analyze="${1:-$repo/.venv/bin/pcdoctor-analyze}"
python="$(dirname "$analyze")/python"
[ -x "$python" ] || python="python3"

cargo build --quiet --manifest-path "$here/Cargo.toml" -j 2
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

"$here/target/debug/pcdoctor-capture" \
  --process Game.exe --seconds 3 --interval 0.5 \
  --presentmon-csv "$here/tests/fixtures/presentmon_game.csv" \
  --lhm-file "$here/tests/fixtures/lhm_intel_nvidia.json" \
  --label "analyzer check" --output-dir "$work/runs"

zip="$(ls "$work"/runs/PCDoctor-run-*.zip)"
mkdir "$work/unzipped"
"$python" -I -m zipfile -e "$zip" "$work/unzipped"
echo "Zip contents: $(ls "$work/unzipped" | tr '\n' ' ')"

status=0
for dir in "$(ls -d "$work"/runs/PCDoctor-run-*/)" "$work/unzipped"; do
  echo "=== $(basename "$dir")"
  "$analyze" "$dir"
  "$analyze" "$dir" --json > "$work/result.json"
  "$python" -I - "$work/result.json" <<'PY' || status=1
import json, re, sys
result = json.load(open(sys.argv[1]))
notes = result.get("notes", [])
unread = [n for n in notes if re.search(r"could not be read|is missing|does not know", n)]
stats = result.get("frame_stats") or {}
print("notes:", notes)
print("frames:", stats.get("frames"), "avg fps:", stats.get("avg_fps"),
      "| sensor columns:", sorted(result.get("sensor_stats", {})))
if unread:
    sys.exit("The analyzer could not read the output: " + "; ".join(unread))
if not stats.get("frames"):
    sys.exit("No frame statistics in the analysis result")
if "cpu_temp_c" not in result.get("sensor_stats", {}):
    sys.exit("No CPU temperature in the analysis result")
print("OK: the analyzer read everything")
PY
done
exit $status
