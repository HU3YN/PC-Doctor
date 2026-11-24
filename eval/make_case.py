"""Turn a run zip into a labeled real case: eval/cases/<name>/.

    python eval/make_case.py run.zip --name 2026-10-25-usb-disk-retry \\
        --expect storage.io_errors --expect stability.bluescreen \\
        --note "USB-C drive was attached; crash was at shutdown" --source owner-pc

The zip is untrusted input. It is checked before anything is written:

  * only the collector's known run files are accepted (an unknown file, an
    absolute path, a ".." or a duplicate refuses the whole zip); the files may
    be at the root of the zip or inside one top-level folder;
  * the number of files and the unpacked size are capped, counting the bytes
    actually read, not the sizes the zip claims;
  * every finding code must exist in the analyzer's rule registry;
  * because the case will be committed, the text is searched for what
    docs/privacy.md says must not be there (another user's folder name, an
    email address, a serial number). A hit refuses the case and prints the
    file, line and what matched, never the whole content. --force overrides
    that check (and only that check, plus overwriting an existing case).

Then the analyzer runs on the case and prints whether the expected findings
fire today. That is the case's first score. A miss is not an error: it is the
information the case exists to give.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath

from pcdoctor_analysis import analyze_run_dir
from pcdoctor_analysis.rules import all_rules

from run_eval import CASES, judge

# Same list as api/pcdoctor_api/services/ingest.py RUN_FILES (a test keeps them equal).
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
MAX_ENTRIES = 50
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# Folder names under C:\Users that are not a person.
SHARED_PROFILES = {"<user>", "public", "default", "default user", "all users"}
USER_FOLDER = re.compile(r"[A-Za-z]:(?:\\{1,4}|/)Users(?:\\{1,4}|/)([^\\/\s\"'<>|]+|<user>)", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
SERIAL = re.compile(
    r"serial\w*(?:\s+(?:number|no\.?))?[\s\"']*[:=][\s\"']*([A-Za-z0-9][A-Za-z0-9._-]{5,})", re.I
)
SERIAL_OK = {"<removed>", "null", "none", "unknown", "true", "false"}


class Refused(Exception):
    """The case cannot be made; the message says why."""


def read_zip(path: Path) -> dict[str, bytes]:
    """The run's files by name, or Refused. Nothing is written to disk."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError) as error:
        raise Refused(f"cannot open {path} as a zip: {error}") from None
    files: dict[str, bytes] = {}
    with archive:
        entries = [e for e in archive.infolist() if not e.is_dir()]
        if len(entries) > MAX_ENTRIES:
            raise Refused(f"the zip has {len(entries)} files; a run has at most 8")
        parts_by_entry = []
        for info in entries:
            raw = info.filename
            if "\\" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
                raise Refused(f"unsafe path in zip: {raw!r}")
            parts = PurePosixPath(raw).parts
            if not parts or ".." in parts or "" in parts or "." in parts:
                raise Refused(f"unsafe path in zip: {raw!r}")
            parts_by_entry.append(parts)
        if not entries:
            raise Refused("the zip has no files")
        depths = {len(p) for p in parts_by_entry}
        if depths == {1} or depths == {2} and len({p[0] for p in parts_by_entry}) == 1:
            pass
        else:
            raise Refused("files must be at the root of the zip or inside one top-level folder")
        total = 0
        for info, parts in zip(entries, parts_by_entry, strict=True):
            name = parts[-1]
            if name not in RUN_FILES:
                raise Refused(
                    f"unknown file in zip: {info.filename!r} (a run has only: "
                    f"{', '.join(sorted(RUN_FILES))})"
                )
            if name in files:
                raise Refused(f"{name} appears twice in the zip")
            if info.flag_bits & 0x1:
                raise Refused("the zip is password-protected")
            if info.file_size > MAX_FILE_BYTES:
                raise Refused(f"{name} is larger than {MAX_FILE_BYTES // 2**20} MB")
            try:
                with archive.open(info) as source:
                    data = source.read(MAX_FILE_BYTES + 1)
            except Exception as error:
                raise Refused(f"cannot read {name}: {error}") from None
            if len(data) > MAX_FILE_BYTES:
                raise Refused(f"{name} is larger than {MAX_FILE_BYTES // 2**20} MB")
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise Refused(f"the run is larger than {MAX_TOTAL_BYTES // 2**20} MB unpacked")
            files[name] = data
    for required in ("manifest.json",):
        if required not in files:
            raise Refused(f"{required} is missing: this does not look like a collector run")
    return files


def privacy_hits(files: dict[str, bytes]) -> list[str]:
    """One short line per match: file, line number and what matched."""
    hits: list[str] = []
    for name, data in sorted(files.items()):
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            for match in USER_FOLDER.finditer(line):
                if match.group(1).lower() not in SHARED_PROFILES:
                    hits.append(f"{name}:{number}: user folder name {match.group(0)!r}")
            for match in EMAIL.finditer(line):
                hits.append(f"{name}:{number}: email address {match.group(0)!r}")
            for match in SERIAL.finditer(line):
                if match.group(1).lower() not in SERIAL_OK:
                    hits.append(
                        f"{name}:{number}: serial-like value after 'serial': "
                        f"{match.group(0)[:40]!r}"
                    )
    return hits


def check_codes(codes: list[str], option: str) -> None:
    known = {r.code for r in all_rules()}
    unknown = sorted(set(codes) - known)
    if unknown:
        raise Refused(
            f"unknown finding code for {option}: {', '.join(unknown)} "
            "(list them with: pcdoctor-analyze rules)"
        )


def build_label(args: argparse.Namespace, zip_sha256: str) -> dict:
    note = (args.note or "").strip()
    label: dict = {
        "expected": list(dict.fromkeys(args.expect)),
        "must_not": list(dict.fromkeys(args.absent)),
        "description": note or args.name,
        "machine": args.source or "",
        "note": note,
        "source": args.source or "",
        "added": date.today().isoformat(),
        "run_zip_sha256": zip_sha256,
    }
    return label


def make_case(args: argparse.Namespace) -> int:
    if not NAME_PATTERN.match(args.name):
        raise Refused("--name must be 1-64 characters: lowercase letters, digits, '.', '_' or '-'")
    if not args.expect and not args.absent:
        raise Refused("give at least one --expect (or --absent) finding code")
    overlap = set(args.expect) & set(args.absent)
    if overlap:
        raise Refused(f"in both --expect and --absent: {', '.join(sorted(overlap))}")
    check_codes(args.expect, "--expect")
    check_codes(args.absent, "--absent")
    target = args.cases_dir / args.name
    if target.exists() and not args.force:
        raise Refused(f"{target} already exists (use --force to replace it)")

    zip_path = Path(args.zip)
    files = read_zip(zip_path)
    hits = privacy_hits(files)
    if hits:
        print("Privacy check found:", file=sys.stderr)
        for hit in hits[:30]:
            print(f"  {hit}", file=sys.stderr)
        if len(hits) > 30:
            print(f"  ... and {len(hits) - 30} more", file=sys.stderr)
        if not args.force:
            raise Refused(
                "refusing to make a case that would be committed with this in it; "
                "fix the run or use --force if you have checked each hit"
            )
        print("  --force given: continuing anyway.", file=sys.stderr)

    label = build_label(args, hashlib.sha256(zip_path.read_bytes()).hexdigest())
    args.cases_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".new-case-", dir=args.cases_dir))
    try:
        for name, data in files.items():
            (staging / name).write_bytes(data)
        (staging / "label.json").write_text(
            json.dumps(label, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    print(f"Wrote {target} ({len(files)} run files + label.json)")
    found = {f.code for f in analyze_run_dir(target).findings}
    ok, _ = judge(found, label["expected"], label["must_not"])
    print("First score on today's rules:")
    for code in label["expected"]:
        print(f"  {'fires ' if code in found else 'MISSED'}  expected {code}")
    for code in label["must_not"]:
        print(f"  {'WRONGLY REPORTED' if code in found else 'absent'}  must_not {code}")
    other = sorted(found - set(label["expected"]) - set(label["must_not"]))
    print(f"  other findings: {', '.join(other) if other else 'none'}")
    print(
        "Case PASSES today." if ok else "Case does not pass today (a miss is useful information)."
    )
    print("Review the files once before committing; then: python eval/run_eval.py --real-only")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("zip", help="the run .zip the collector made")
    parser.add_argument("--name", required=True, help="case folder name, e.g. 2026-10-25-usb-disk")
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="CODE",
        help="a finding code a correct diagnosis must contain (repeatable)",
    )
    parser.add_argument(
        "--absent",
        action="append",
        default=[],
        metavar="CODE",
        help="a finding code that must NOT appear (label 'must_not'; repeatable)",
    )
    parser.add_argument("--note", default="", help="free text: what was wrong, who confirmed it")
    parser.add_argument("--source", default="", help="which machine the run came from")
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing case; accept privacy hits"
    )
    parser.add_argument("--cases-dir", type=Path, default=CASES, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        return make_case(args)
    except Refused as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
