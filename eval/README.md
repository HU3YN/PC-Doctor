# eval

Labeled fault cases and the harness that scores the diagnosis against them.

```bash
python eval/run_eval.py              # every case
python eval/run_eval.py --real-only  # only real captures - the number that counts
```

Real cases go in `eval/cases/<name>/` (a run folder plus `label.json`).
How to make them safely: [docs/fault-testing.md](../docs/fault-testing.md).

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
by the script and cropped to the screen; they have none of what makes a real
photo hard (glare, focus, a curved screen, moire, a bezel or desk in the
frame). Its counts are a plumbing check and must never be quoted as a read
rate.

One thing seen while building the plumbing check, to look at with real photos:
on drawn images, a dark border around the screen (a bezel, a desk) made the
reader return no text at all. Real phone photos usually have one.

**Not verified:** there are no real phone photos yet, so there is no measured
read rate for the photo reader.

Tests (no Tesseract needed except for one end-to-end test, which is skipped
without it):

```bash
python -m pytest eval/tests -q
```
