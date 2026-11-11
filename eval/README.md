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
