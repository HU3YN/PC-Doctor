# eval/photos - real photos for measuring the photo reader

Put phone photos of error screens here, list them in `labels.csv`, and run:

```bash
python eval/photo_eval.py
```

Each photo goes through the same code the server runs on an upload
(`photo.read_text`, then `errortext.interpret`) and the stop code found is
compared with your label. You get one line per photo and counts such as
"read correctly: 7 of 9".

**There are no real photos yet, so there is no measured read rate.** When
there is one, it is recorded in `docs/results.md` as counts, together with
how many photos it is based on.

## What to photograph - and what never to

Photograph **the screen or the board only**.

Never include:

- people (faces, hands, reflections of a person in a glossy screen),
- paperwork, invoices, notes, post-its,
- serial-number or service-tag stickers, Windows licence stickers, asset tags,
- anything else that identifies an owner: a user name on a sign-in screen, an
  email address, a desk with personal items, a window with a view.

If any of that is in the frame, retake the photo closer. Do not try to fix a
photo afterwards.

**Strip nothing by hand.** The script only reads the files: it re-encodes
nothing, moves nothing and uploads nothing. Phone photos carry hidden details
(time, phone model, sometimes GPS position); they stay inside the file on this
computer, and the files are git-ignored, so they are never committed. If a
photo ever has to leave this computer, send it through the app's photo inbox,
which removes those details.

## Labels

Copy `labels.example.csv` to `labels.csv` and write one line per photo:

| column | what goes in it |
|---|---|
| `file` | the file name in this folder (`bsod-desk-01.jpg`) |
| `stop_code` | the code on the screen as hex (`0x124`). Look the name up on the **Look up** page if the screen shows only a name. **Leave empty when the photo shows no stop code.** |
| `source` | the kind of screen, in your own words: `LCD monitor`, `laptop screen`, `TV`, `BIOS screen` |
| `notes` | anything that might explain a bad read: angle, glare, distance. No names, no customer details. |

Write the label from the screen itself, before running the script, so the
reader's answer cannot influence it.

Include photos with **no** stop code (boot menus, BIOS screens, a black screen
with a message). They measure how often the reader invents a code.

`labels.csv` is git-ignored together with the photos.

## Reading the result

| group | meaning |
|---|---|
| read correctly | the label's code was found and no other |
| read WRONGLY | a code was reported that is not the label's. This is worse than no code - it sends you down the wrong path - so it is counted on its own. |
| not read | no code was found |
| could not open | the reader refused the file |
| code INVENTED | a photo with no stop code got one anyway |

Take photos the way they are really taken at the bench - different screens,
angles, distances, lighting - not only the easy ones. A few dozen photos give
a first impression; with fewer than about 30 the script says so and the counts
should be reported as they are, not as a rate.

## Plumbing check

```bash
python eval/photo_eval.py --synthetic 40
```

draws 40 error screens and scores them. It shows that the script and the OCR
engine are connected. It is **not** a read rate: a drawn image has no glare,
no focus problems and no curved screen. Never quote its numbers as a result.
