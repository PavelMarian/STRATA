# STRATA

Layered point-in-time (PIT) checks for ML pipelines over time-stamped
relational data, made for code written by coding agents.

A layer is PIT-correct at time `t` if its output is the same on the data as
it is now and on the data as it was at `t`. STRATA runs every layer both ways
and compares outputs; it never reads the code under test.

| Layer | Intervention | Compared output |
|---|---|---|
| task | entity creation vs. row time; labels on `D` vs. `D|(t+h)`; split order | task rows, labels |
| features | `D` vs. `D|t`; canary `D'` with a different future and the same past; unknown-column probe | feature frame |
| model | history with labels known by `t` vs. history with later rows | predictions on the query |
| icl | context pool up to `t` vs. pool with later examples | predictions on the query |
| agent | original vs. order-preserving anonymised identities | predictions on the query |

Verdicts: `CLEAN` (no difference at the tested times), `LEAK` (with a
witness: time, entity, column, channel), `UNCHECKABLE` (missing availability
information, unknown-availability column read, nondeterministic program),
`ERROR`. Exit codes 0/1/2/3.

The database enters only through `schema.json` (see `strata/schema.py` for the
format; `strata init` drafts one). `SKILL.md` is the instruction file for
coding agents.

`strata init --llm` lets an LLM propose the schema from a profile of the files
(and `--docs` documentation): row times, late-filled and planned dates,
snapshot and mutable columns, entities, each with a reason. Every decision is
checked against the data, contradictions go back to the model (`--rounds`),
and the draft lists decisions, open findings and questions under `_review`.
The model never produces a verdict or code; checks run on the reviewed file.
The model is called through OpenRouter (`OPENROUTER_API_KEY`, `--model`, default
`anthropic/claude-opus-5.5`, JSON-schema response format) using only the
standard library. `--no-samples` keeps sample values local.

```bash
pip install -e .                      # pandas, numpy; pyarrow for parquet
strata init --data path/to/csvs --out schema.json
strata check features --schema schema.json --program feats.py:get_features --entity customer
python -m pytest tests                # 38 tests over a synthetic database
```

## Layout

| Path | Contents |
|---|---|
| `strata/` | the package: schema and temporal database, layer checks, verdicts, sandbox, CLI, schema drafting (heuristic and LLM) |
| `tests/` | tests over a synthetic database |
| `examples/olist/` | Olist schema and the replay of 134 generated feature programs |
| `examples/pitbench/` | PITBench controls, mutation testing, baselines, schema drafting evaluation |
| `examples/relbench/` | replay of 27 agent-written training runs on RelBench F1 and Event |
| `results/` | raw outputs and summaries of all experiments; see `results/README.md` |
| `SKILL.md` | instruction file for coding agents |

## Results

| Experiment | Result |
|---|---|
| PITBench controls (8 databases, 34 programs) | 34/34 verdicts as expected |
| PITBench mutants (98 live, 43 violations, 55 harmless) | 43/43 violations killed, 0/55 harmless flagged |
| Baselines on the same controls | rows cut at t: 11/25 leaks; + late dates and canary: 16/25; max-AUC rules: 4-5/25 with 3/9 false alarms |
| Olist, 134 generated feature programs | 62/63 oracle leaks confirmed, 16 leaks the oracle misses |
| RelBench, 27 agent training runs | model layer LEAK in 27/27 |
| Schema drafting vs hand-made maps | heuristic: 5/50 snapshot columns caught; LLM agent: 50/50 |
