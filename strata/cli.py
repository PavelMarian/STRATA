"""strata -- layered point-in-time checks for ML pipelines.

    strata init     --data DIR --out schema.json
    strata check features --schema S --program f.py:get_features --entity E [--times ...]
    strata check task     --task T.csv --time-col C --entity-col C [--schema S --entity E]
                          [--label-program f.py:label --horizon-days H] [--splits a=..,b=..]
    strata check model    --data train.parquet --time-col C --entity-col C --target-col C
                          (--cmd "python solution.py --task-dir {task_dir} ... --out {out}"
                           | --program f.py:predict) [--horizon-days H]
    strata check icl      (same as model; the history is the context pool)
    strata check agent    --data train.parquet --query q.parquet ... (--cmd ... | --program ...)

Exit codes: 0 CLEAN, 1 LEAK, 2 UNCHECKABLE, 3 ERROR. A JSON report is written
with --report; the summary goes to stdout.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import checks
from .infer import write_draft
from .schema import Schema, TemporalDB


def _read(path):
    path = str(path)
    return pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)


def _times(arg, db=None, k=3):
    if arg:
        return [pd.Timestamp(x) for x in arg.split(",")]
    lo, hi = db.time_range()
    return [lo + (hi - lo) * q for q in (0.5, 0.7, 0.9)][:k]


def _runner(a, cols):
    fmt = "parquet" if str(a.data).endswith(".parquet") else "csv"
    return checks.Runner(cmd=a.cmd, program=a.program, pred_col=a.pred_col, fmt=fmt,
                         timeout=a.timeout, mem_mb=a.mem_mb, cols=cols,
                         hide_query_target=a.hide_query_target)


def main(argv=None):
    p = argparse.ArgumentParser(prog="strata", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd_", required=True)

    pi = sub.add_parser("init", help="draft an availability schema for a data directory")
    pi.add_argument("--data", required=True)
    pi.add_argument("--out", required=True)
    pi.add_argument("--name")
    pi.add_argument("--llm", action="store_true",
                    help="let an LLM (via OpenRouter, key in OPENROUTER_API_KEY) propose the schema; "
                         "decisions are checked against the data and listed for review "
                         "(sends a data profile to the provider)")
    pi.add_argument("--docs", help="documentation of the data to give the model (text/markdown)")
    pi.add_argument("--no-samples", action="store_true", help="send no sample values to the model")
    pi.add_argument("--model", default="anthropic/claude-opus-5.5", help="OpenRouter model id")
    pi.add_argument("--rounds", type=int, default=2, help="revision rounds after the data check")

    pc = sub.add_parser("check", help="run one layer check")
    pc.add_argument("layer", choices=["task", "features", "model", "icl", "agent"])
    pc.add_argument("--schema")
    pc.add_argument("--program", help="FILE.py:FUNCTION")
    pc.add_argument("--cmd", help="command template with {task_dir} {out} {split} {train} {query} ...")
    pc.add_argument("--entity", help="entity name from the schema")
    pc.add_argument("--n-entities", type=int, default=15)
    pc.add_argument("--times", help="comma-separated prediction times")
    pc.add_argument("--task", help="task table (task layer)")
    pc.add_argument("--splits", help="name=path,... in chronological order (task layer)")
    pc.add_argument("--label-program", help="FILE.py:FUNCTION (task layer)")
    pc.add_argument("--data", help="history table: training rows or context pool")
    pc.add_argument("--query", help="query table (agent layer)")
    pc.add_argument("--time-col")
    pc.add_argument("--entity-col")
    pc.add_argument("--target-col")
    pc.add_argument("--id-cols", default="", help="extra identity columns (agent layer)")
    pc.add_argument("--shift-days", type=int, default=0, help="date shift (agent layer)")
    pc.add_argument("--horizon-days", type=float, default=0)
    pc.add_argument("--pred-col")
    pc.add_argument("--hide-query-target", action="store_true")
    pc.add_argument("--atol", type=float)
    pc.add_argument("--timeout", type=int, default=600)
    pc.add_argument("--mem-mb", type=int, default=4096)
    pc.add_argument("--no-canary", action="store_true")
    pc.add_argument("--report", help="write the JSON report here")
    pc.add_argument("--json", action="store_true", help="print the JSON report instead of a summary")
    a = p.parse_args(argv)

    if a.cmd_ == "init":
        if a.llm:
            import json as _json
            from .llm_init import SchemaAgentError, llm_schema
            try:
                d = llm_schema(a.data, docs=a.docs, samples=not a.no_samples, model=a.model,
                               rounds=a.rounds)
            except SchemaAgentError as e:
                print(f"strata init --llm: {e}", file=sys.stderr)
                return 3
            Path(a.out).write_text(_json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            d = write_draft(a.data, a.out, a.name)
        print(f"draft schema written to {a.out}; review these decisions:")
        for r in d["_review"]:
            print("  -", r)
        return 0

    db = None
    if a.schema:
        try:
            db = TemporalDB.load(Schema.load(a.schema))
        except (OSError, ValueError, KeyError) as e:
            print(f"strata: cannot load schema {a.schema}: {e}", file=sys.stderr)
            return 3
    cols = {k: v for k, v in dict(time_col=a.time_col, entity_col=a.entity_col,
                                  target_col=a.target_col).items() if v}

    if a.layer == "features":
        if db is None or not a.program or not a.entity:
            p.error("features needs --schema, --program and --entity")
        rep = checks.check_features(db, a.program, _times(a.times, db), a.entity, a.n_entities,
                                    atol=a.atol or 1e-9, timeout=a.timeout, mem_mb=a.mem_mb,
                                    canary=not a.no_canary)
    elif a.layer == "task":
        splits = None
        if a.splits:
            splits = {kv.split("=", 1)[0]: _read(kv.split("=", 1)[1]) for kv in a.splits.split(",")}
        task = _read(a.task) if a.task else pd.concat(list(splits.values()), ignore_index=True)
        rep = checks.check_task(task, a.time_col, a.entity_col, db, a.entity, splits,
                                a.label_program, a.horizon_days or None,
                                timeout=a.timeout, mem_mb=a.mem_mb, atol=a.atol or 1e-9)
    elif a.layer in ("model", "icl"):
        data = _read(a.data)
        rep = checks.check_history(a.layer, _runner(a, cols), data, a.time_col, a.entity_col,
                                   a.target_col, a.horizon_days,
                                   query_times=[pd.Timestamp(x) for x in a.times.split(",")]
                                   if a.times else None, atol=a.atol or 1e-6)
    else:  # agent
        train, query = _read(a.data), _read(a.query)
        ids = [c for c in a.id_cols.split(",") if c]
        rep = checks.check_agent(_runner(a, cols), train, query, a.entity_col, a.time_col,
                                 a.target_col, ids, a.shift_days, atol=a.atol or 1e-6)

    if a.report:
        Path(a.report).write_text(rep.to_json(), encoding="utf-8")
    print(rep.to_json() if a.json else rep.summary())
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
