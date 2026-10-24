"""Python side of demo/alt/live.html. Runs inside Pyodide (or any Python with
STRATA_INPROCESS=1). The page calls these functions and renders what comes back.

    setup(schema_json, data_dir)        -> {"tables": {name: [columns]}, "time_range": [lo, hi]}
    run_features(code, times, n)        -> {"summary", "verdict", "exit", "witnesses", "probes", "notes"}
    schema_messages(data_dir, samples)  -> {"system", "user", "output_schema"}
    schema_round(data_dir, text)        -> {"schema", "findings", "review"}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from strata import checks
from strata.evidence import check_schema
from strata.infer import infer_schema
from strata.llm_init import OUTPUT_SCHEMA, SYSTEM, to_schema
from strata.profile import profile
from strata.schema import Schema, TemporalDB

DB = None
PROGRAM = Path("/tmp/live_program.py")


def setup(schema_json: str, data_dir: str):
    global DB
    raw = json.loads(schema_json)
    raw["root"] = data_dir
    DB = TemporalDB.load(Schema.from_dict(raw, base=data_dir))
    lo, hi = DB.time_range()
    return json.dumps({"tables": {k: list(v.columns) for k, v in DB.tables.items()},
                       "time_range": [str(lo), str(hi)]})


def run_features(code: str, times: str, n: int = 8):
    PROGRAM.write_text(code, encoding="utf-8")
    ts = [pd.Timestamp(x) for x in times.split(",")]
    rep = checks.check_features(DB, f"{PROGRAM}:get_features", ts, "product", n_entities=int(n))
    d = rep.to_dict()
    return json.dumps({"summary": rep.summary(), "verdict": d["status"],
                       "exit": rep.exit_code, "witnesses": d.get("witnesses", []),
                       "probes": d.get("probes", []), "notes": d.get("notes", [])}, default=str)


def schema_messages(data_dir: str, samples: bool = True):
    prof = profile(Path(data_dir), samples=samples)
    heur = {k: v for k, v in infer_schema(Path(data_dir)).items() if k != "root"}
    user = ("Profile of the data files (sampled rows):\n" + json.dumps(prof, indent=1, default=str)
            + "\n\nDraft from STRATA's name/date heuristics, with its decisions under _review "
              "(a starting point; correct it where it is wrong):\n" + json.dumps(heur, indent=1))
    return json.dumps({"system": SYSTEM, "user": user, "output_schema": OUTPUT_SCHEMA})


def schema_round(data_dir: str, text: str):
    data_dir = Path(data_dir)
    proposal = json.loads(text)
    prof = profile(data_dir, samples=False)
    files = {t: p["file"] for t, p in prof.items()}
    dates = {t: [c for c, i in p["columns"].items() if i["dtype"] == "date"] for t, p in prof.items()}
    schema = to_schema(proposal, files, data_dir, dates)
    findings = check_schema(schema, data_dir)
    review = ([f"{t['name']}: {t['kind']}"
               + (f" (time {t['time']})" if t["kind"] == "timed" else "")
               + (f" (from {t['inherits_from']} via {t['inherits_key']})" if t["kind"] == "inherits" else "")
               + f" -- {t['reason']}" for t in proposal["tables"]]
              + [f"entity {e['name']} = {e['table']}.{e['key']}, created {e['created'] or 'unknown'}"
                 f" -- {e['reason']}" for e in proposal["entities"]])
    return json.dumps({"schema": schema, "findings": findings, "review": review,
                       "questions": proposal.get("questions", [])}, default=str)


if __name__ == "__main__":                       # local smoke test: python live_glue.py <strata dir>
    root = Path(sys.argv[1])
    print(setup((root / "examples/olist/schema.json").read_text(), str(root / "demo/alt/data/olist"))[:300])
    code = (root / "demo/alt/data.js").read_text()
    import re
    prog = json.loads(re.search(r"^const PROG = (.*);$", code, re.M).group(1))
    for name in ("leaky", "fixed", "status"):
        r = json.loads(run_features(prog[name], "2018-01-01,2018-04-01", 8))
        print(name, r["exit"], r["summary"].splitlines()[0])
    m = json.loads(schema_messages(str(root / "demo/alt/data/olist")))
    print("user prompt chars", len(m["user"]))
