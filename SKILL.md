---
name: strata
description: Check an ML pipeline over time-stamped data for point-in-time leakage (look-ahead, future leakage) layer by layer -- task table and labels, feature code, model training, in-context examples, and identity recall -- by running each layer on the data as it was at prediction time and as it is now. Use it whenever you write or review code that builds a prediction task, computes features, trains a model or assembles few-shot examples from data with timestamps, before you report a score, and whenever someone asks whether a pipeline "uses the future", leaks, or is point-in-time correct.
---

# STRATA: layered point-in-time checks

STRATA decides leakage by execution, not by reading code. Run it; do not
replace its verdict with your own reading. Install: `pip install -e <strata dir>`
(gives the `strata` command; `python -m strata` works too).

## 0. Describe the database once

```bash
strata init --data <dir with .csv/.parquet> --out schema.json
```

The draft lists every decision under `_review`. Confirm each one against the
data documentation and edit `schema.json`:

- `time`: when a row becomes known. `time_from`: a table without its own time
  inherits it through a key. `static`: a reference table.
- `self_available`: a date column known only at its own value (delivery date).
- `value_time`: `{column: stamp}` for a value filled in later than its row.
- `unknown`: mutable columns without history (status). Never guess these away.
- `entities`: `{name: {table, key, created}}`; `created` enables the task check.

## 1. Check the layers you wrote

| Layer | When | Command |
|---|---|---|
| task | you built a task table / labels | `strata check task --task T --time-col C --entity-col C --schema schema.json --entity E [--label-program f.py:label --horizon-days H]` |
| features | you wrote `get_features(db, ids, t)` | `strata check features --schema schema.json --program f.py:get_features --entity E` |
| model | you wrote a training script | `strata check model --data train.parquet --time-col C --entity-col C --target-col C --horizon-days H --cmd "python solution.py --task-dir {task_dir} --split {split} --out {out}"` |
| icl | you select few-shot examples | `strata check icl --data pool.parquet ... --program f.py:predict` |
| agent | the predictor calls an LLM or a lookup | `strata check agent --data train.parquet --query q.parquet ... --cmd ...` |

Contracts: `get_features(tables: dict[str, DataFrame], entity_ids, t) -> DataFrame`
indexed by entity; `label(tables, entity_ids, t) -> Series`; `predict(history,
query) -> one score per query row`. A script is run with the placeholders
`{task_dir}` (holds `train` and `val`/`test` files), `{split}`, `{out}` (CSV with
one numeric prediction column; name it with `--pred-col`), `{time_col}`,
`{entity_col}`, `{target_col}`, `{train}`, `{query}`.

## 2. Read the verdict

Exit code and the first line: `CLEAN` 0, `LEAK` 1, `UNCHECKABLE` 2, `ERROR` 3.
Use `--json` or `--report r.json` for the machine-readable report.

- `LEAK`: fix it. The witness names the time, the entity, the column and, for
  features, the channel (table rows or a late-filled column) that carried the
  future. Re-run the same command after the fix; only a re-run may declare it
  fixed.
- `UNCHECKABLE`: say so in your answer. Typical causes: the output depends on a
  column with unknown availability, the entity has no creation time, the
  program is nondeterministic (fix the seed and re-run).
- `ERROR`: the program crashed in the sandbox; fix it and re-run.
- `CLEAN`: no difference at the tested times. Report it as exactly that, not as
  a proof that the pipeline is leak-free.

## Safety

STRATA executes the code under test in a child process with a timeout and a
memory limit and strips `*API_KEY*`, `*TOKEN*`, `*SECRET*` variables from its
environment. Do not pass credentials to it.
