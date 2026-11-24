# eval

Labeled fault cases and the harness that scores the diagnosis against them.

```bash
python eval/run_eval.py              # every case
python eval/run_eval.py --real-only  # only real captures - the number that counts
```

Real cases go in `eval/cases/<name>/` (a run folder plus `label.json`).
How to make them safely: [docs/fault-testing.md](../docs/fault-testing.md).

## Add a real case: `make_case.py`

One command turns a run zip into `eval/cases/<name>/` (the run files plus
`label.json`) and prints the case's first score on today's rules. For the
25 October run (disk retry on Disk 3, a USB-C drive; stop code 0x9F at shutdown):

```bash
python eval/make_case.py path/to/run.zip --name 2026-10-25-usb-disk-0x9f \
    --expect storage.io_errors --expect stability.bluescreen \
    --source owner-pc \
    --note "Owner confirmed a USB-C drive was attached (Disk 3) and the crash happened at shutdown."
```

- `--expect CODE` (repeatable): a finding a correct diagnosis must contain.
  `--absent CODE` (repeatable): one it must not (`must_not` in the label).
  Codes are checked against the rule registry (`pcdoctor-analyze rules`).
- The zip is treated as untrusted: only the collector's known files, at the
  root or in one top-level folder, no `..` or absolute paths, size capped.
- Privacy check: because cases are committed, it refuses a run that contains
  another user's folder name (`C:\Users\name`), an email address or a serial
  number after the word "serial", and prints file and line (not the content).
  `--force` accepts those hits and also replaces an existing case; without it
  an existing case is never overwritten.
- A miss in the printed score is not an error; it is what the case is for.
  Check it with `python eval/run_eval.py --real-only`, then read the files once
  before committing.

Example `label.json`:

```json
{
  "expected": ["storage.io_errors", "stability.bluescreen"],
  "must_not": [],
  "description": "Owner confirmed a USB-C drive was attached (Disk 3) ...",
  "machine": "owner-pc",
  "note": "Owner confirmed a USB-C drive was attached (Disk 3) ...",
  "source": "owner-pc",
  "added": "2026-11-24",
  "run_zip_sha256": "..."
}
```

`run_eval.py` reads `expected`, `must_not`, `description` and `machine`; the
other fields are for people.

There are no real cases yet. The built-in synthetic cases only prove the
pipeline runs; never quote their score as accuracy.

## Photo reader: `photo_eval.py`

Scores the photo reader - the part that reads a stop code off a phone photo
of an error screen - against photos you have labeled by hand.

```bash
python eval/photo_eval.py                  # eval/photos/ and its labels.csv
python eval/photo_eval.py path/to/folder   # another folder with a labels.csv
python eval/photo_eval.py --synthetic 40   # plumbing check on drawn images
```

It needs the Tesseract OCR program (`apt-get install tesseract-ocr`, or the
UB-Mannheim installer on Windows) and `pip install -e workers -e "api[dev]"`. Without
Tesseract it says so and exits with code 2.

Each photo goes through the server's own functions, the same ones
`POST /api/photos` calls: `pcdoctor_api.services.photo.read_text`, then
`pcdoctor_analysis.errortext.interpret`. Nothing is re-implemented, so what
is scored is what the server would show.

Every photo lands in one group, and each group is reported as a count
("N of M"), never as a bare percentage:

- photos labeled with a stop code: **read correctly**, **read WRONGLY**
  (a code other than the label's - counted on its own, because a wrong code
  sends the technician the wrong way), **not read** (no code found),
  **could not open**;
- photos labeled with no stop code: **nothing reported** or **code INVENTED**.

How to take and label the photos, and what must never be in them:
[photos/README.md](photos/README.md). The photos and `labels.csv` are
git-ignored and never leave this computer.

**What `--synthetic` proves:** only that the script, the OCR engine and the
code finder are connected and that the scoring adds up. The images are drawn
by the script; they have none of what makes a real
photo hard (glare, focus, a curved screen, moire, a bezel or desk in the
frame). Its counts are a plumbing check and must never be quoted as a read
rate.

Found while building the plumbing check, and fixed: on drawn images, a dark
border around the screen (a bezel, a desk) or a 2 degree tilt made the reader
return no text at all. The reader now cuts the photo down to the lit screen
first (`crop_to_screen` in `api/pcdoctor_api/services/photo.py`), and
`api/tests/test_intake.py` keeps it that way. Whether that is enough for real
photos is still to be measured.

**Not verified:** there are no real phone photos yet, so there is no measured
read rate for the photo reader.

Tests (no Tesseract needed except for one end-to-end test, which is skipped
without it):

```bash
python -m pytest eval/tests -q
```
