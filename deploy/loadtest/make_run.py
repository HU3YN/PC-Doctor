"""Write a made-up sample run for the load test: deploy/loadtest/run.zip."""

from pathlib import Path

from pcdoctor_analysis import synth

target = Path(__file__).parent / "run.zip"
target.write_bytes(synth.build("cpu_overheat").zip_bytes())
print(f"wrote {target} ({target.stat().st_size // 1024} KB)")
