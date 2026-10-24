"""Baselines on the PITBench controls and mutants, next to STRATA.

    python baselines.py --pitbench P --controls-out b_controls.jsonl
    python baselines.py --pitbench P --mutants ../../results/pitbench/mutants.jsonl   (mutant baselines)

Controls (ground truth: dataset.json expectations; snapshot controls are leaks):
  row_cut      STRATA oracle with the schema reduced to row times: rows cut at t,
               no late values, no snapshots, no canary (Featuretools-style cutoff,
               the earlier single-database oracle)
  v1           row times + late-filled dates + canary, snapshots not declared
               (the pit-check v1 semantics)
  auc_dr/h2o   max single-feature AUC on the full database > 0.85 / 0.80 at any
               time (DataRobot / H2O target-leakage rules)
  lint         static: the code names a late or snapshot column, or never compares
               anything with the prediction time
Mutants (ground truth: PITBench manual triage):
  features_only  only get_features is checked (a single-layer checker)
  any_change     any output change counts as a leak (regression / diff testing)
  lint           the static rule above on the mutated code
"""
import argparse
import ast
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from run_controls import ALL, map_to_schema  # noqa: E402
from strata import Schema, TemporalDB, check_features  # noqa: E402
from strata.sandbox import call_isolated, load_callable  # noqa: E402

TIME_NAMES = {"seed_time", "t", "ti", "t0", "cutoff", "cut", "hi", "lo", "now", "as_of"}


def late_columns(amap):
    cols = set()
    for c in amap.get("self_availability_cols", {}).values():
        cols |= set(c)
    for spec in (amap.get("snapshot_cols") or {}).values():
        cols |= set(spec)
    return cols


def lint(code, late):
    tree = ast.parse(code)
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    reads_late = bool((strings | attrs) & late)
    names_in_cmp = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            names_in_cmp |= {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}
    return reads_late or not (names_in_cmp & TIME_NAMES)


def reduce_schema(raw, keep_self, keep_snapshot):
    raw = json.loads(json.dumps(raw))
    for spec in raw["tables"].values():
        if not keep_self:
            spec.pop("self_available", None)
        if not keep_snapshot:
            spec.pop("value_time", None)
            spec.pop("unknown", None)
    return raw


def max_auc(X, y):
    from strata.checks import _auc
    best = 0.5
    for c in X.columns:
        x = pd.to_numeric(X[c], errors="coerce")
        if x.notna().sum() < 5:
            continue
        a = _auc(y.to_numpy(float), x.fillna(x.median()).to_numpy(float))
        if a is not None:
            best = max(best, a, 1 - a)
    return best


def controls(pb, out_path):
    sys.path.insert(0, str(pb))
    from lib.tasks import LABELS
    with open(out_path, "w") as out:
        for ds in ALL:
            man = json.load(open(pb / "datasets" / ds / "dataset.json"))
            amap = json.load(open(pb / "datasets" / ds / man["availability_map"]))
            raw = map_to_schema(ds, amap, pb / man["data_dir"])
            full = TemporalDB.load(Schema.from_dict(raw))
            dbs = {"row_cut": TemporalDB(Schema.from_dict(reduce_schema(raw, False, False)),
                                         full.tables, full.row_time),
                   "v1": TemporalDB(Schema.from_dict(reduce_schema(raw, True, False)),
                                    full.tables, full.row_time)}
            ent = man["entity"]
            pool = np.sort(full.tables[ent["table"]][ent["column"]].dropna().unique())
            ids = np.sort(np.random.RandomState(0).choice(pool, size=min(ent["n_entities"], len(pool)),
                                                          replace=False))
            times = [pd.Timestamp(s) for s in man["seeds"]["dev"] + man["seeds"]["held_out"]]
            label = LABELS[man["tasks"][0]["name"]]
            late = late_columns(amap)
            for name, spec in man["controls"].items():
                path = pb / "datasets" / ds / "controls" / name
                prog = load_callable(f"{path}:get_features")
                e = spec["expected"]
                truth = e["pit_check"]["verdict"] == "LEAK" or bool(e.get("snapshot_ext"))
                row = {"dataset": ds, "control": name, "class": spec.get("class"), "leak": truth}
                row["row_cut"] = check_features(dbs["row_cut"], prog, times, lambda t: ids,
                                                timeout=300, localize=False, canary=False).status == "LEAK"
                row["v1"] = check_features(dbs["v1"], prog, times, lambda t: ids,
                                           timeout=300, localize=False).status == "LEAK"
                aucs = []
                for t in times:
                    X = call_isolated(prog, (full.tables, ids, t), 300)
                    y = label(full.tables, ids, t).reindex(X.index)
                    aucs.append(max_auc(X, y))
                row["max_auc"] = round(max(aucs), 4)
                row["auc_dr"] = row["max_auc"] > 0.85
                row["auc_h2o"] = row["max_auc"] > 0.80
                row["lint"] = lint(path.read_text(), late)
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(ds, name, {k: row[k] for k in ("leak", "row_cut", "v1", "auc_dr", "auc_h2o", "lint")},
                      flush=True)


def score(rows, key):
    pos = [r for r in rows if r["leak"]]
    neg = [r for r in rows if not r["leak"]]
    return f"{sum(r[key] for r in pos)}/{len(pos)} leaks, {sum(r[key] for r in neg)}/{len(neg)} false"


def mutants(pb, path):
    sys.path.insert(0, str(pb))
    rows = [json.loads(l) for l in open(path)]
    live = [r for r in rows if r["verdict"] in ("KILLED", "SURVIVED") and "pit_violation" in r]
    late_by_ds = {}
    for r in live:
        ds = r["dataset"]
        if ds not in late_by_ds:
            man = json.load(open(pb / "datasets" / ds / "dataset.json"))
            late_by_ds[ds] = late_columns(json.load(open(pb / "datasets" / ds / man["availability_map"])))
    from mutate.mutations import mutants as gen
    codes = {}
    for ds in late_by_ds:
        code = (pb / "datasets" / ds / "layers" / "reference_pipeline.py").read_text()
        codes[ds] = {k: m[4] for k, m in enumerate(gen(code))}
    res = {"strata": [], "features_only": [], "any_change": [], "lint": []}
    for r in live:
        res["strata"].append(r["verdict"] == "KILLED")
        res["features_only"].append(r["layers"]["get_features"] == "LEAK")
        res["any_change"].append(True)
        res["lint"].append(lint(codes[r["dataset"]][r["id"]], late_by_ds[r["dataset"]]))
    v = [r["pit_violation"] for r in live]
    for k, flags in res.items():
        tp = sum(f and t for f, t in zip(flags, v))
        fp = sum(f and not t for f, t in zip(flags, v))
        print(f"{k:14s} violations killed {tp}/{sum(v)}  false alarms {fp}/{len(v) - sum(v)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitbench", required=True)
    ap.add_argument("--controls-out")
    ap.add_argument("--mutants")
    a = ap.parse_args()
    pb = Path(a.pitbench)
    if a.controls_out:
        controls(pb, a.controls_out)
        rows = [json.loads(l) for l in open(a.controls_out)]
        for k in ("row_cut", "v1", "auc_dr", "auc_h2o", "lint"):
            print(f"{k:8s} {score(rows, k)}")
    if a.mutants:
        mutants(pb, a.mutants)


if __name__ == "__main__":
    main()
