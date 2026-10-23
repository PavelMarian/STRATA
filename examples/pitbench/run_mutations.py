"""Mutation testing of STRATA on PITBench reference pipelines.

    python run_mutations.py --pitbench /path/to/pitbench --out mut.jsonl [ds ...]

Each dataset has a reference pipeline with four functions
(select_entities, make_label, get_features, fit_predict). PITBench's mutation
operators (mutate/mutations.py) change one time comparison or offset at a
time; its manual triage (mutate/triage_reference.json) says whether each
behaviour-changing mutant is a point-in-time violation.

Every mutant that changes some output on the full database is checked by
STRATA, layer by layer:

  select_entities, get_features, fit_predict   features check: D vs D|t (+ canary)
  make_label                                   task check: labels on D vs D|(t+h)

A mutant is KILLED if any check reports LEAK. Recall = violations killed;
false alarms = non-violations killed.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from run_controls import map_to_schema  # noqa: E402
from strata import LEAK, Schema, TemporalDB, check_features, check_task  # noqa: E402
from strata.compare import frame_diff  # noqa: E402

ALL = ["olist", "f1", "pkdd99", "adventureworks", "northwind", "sakila", "movietweetings", "tpch"]


def namespace(code):
    ns = {}
    exec(compile(code, "<pipeline>", "exec"), ns)  # noqa: S102 -- reference pipelines and their mutants
    return ns


def as_frame(fn_name, ns):
    """Wrap a pipeline function as program(db, ids, t) -> DataFrame."""
    if fn_name == "select_entities":
        def prog(db, ids, t):
            sel = ns["select_entities"](db, t)
            return pd.DataFrame({"selected": 1.0}, index=pd.Index(sorted(map(str, sel))))
    else:
        def prog(db, ids, t):
            return ns[fn_name](db, ids, t)
    return prog


def outputs(ns, db, ids, seeds):
    out = {}
    for s in seeds:
        for f in ("select_entities", "make_label", "get_features", "fit_predict"):
            out[(s, f)] = as_frame(f, ns)(db.tables, ids[s], pd.Timestamp(s))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitbench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("datasets", nargs="*", default=ALL)
    a = ap.parse_args()
    pb = Path(a.pitbench)
    sys.path.insert(0, str(pb))
    from lib.sampling import ids_by_seed
    from mutate.mutations import DESIGNED_TO_VIOLATE, mutants

    triage = {(t["operator"], t["before"], t["after"]): t
              for t in json.load(open(pb / "mutate" / "triage_reference.json"))["labels"]}
    with open(a.out, "w") as out:
        for ds in a.datasets:
            man = json.load(open(pb / "datasets" / ds / "dataset.json"))
            amap = json.load(open(pb / "datasets" / ds / man["availability_map"]))
            db = TemporalDB.load(Schema.from_dict(map_to_schema(ds, amap, pb / man["data_dir"])))
            exp = json.load(open(pb / "datasets" / ds / "layers" / "expected.json"))
            seeds = man["seeds"]["dev"] + man["seeds"]["held_out"]
            times = [pd.Timestamp(s) for s in seeds]
            ids = ids_by_seed(db.tables, seeds, exp["entity"], man["entity"]["n_entities"])
            ids_t = {pd.Timestamp(s): v for s, v in ids.items()}
            key, H = exp["entity"]["key"], exp["horizon_days"]
            task = pd.DataFrame([(e, pd.Timestamp(s)) for s, v in ids.items() for e in v],
                                columns=[key, "t"])
            code = (pb / "datasets" / ds / "layers" / "reference_pipeline.py").read_text()
            base = outputs(namespace(code), db, ids, seeds)
            with tempfile.TemporaryDirectory() as tmp:
                for k, (op, line, before, after, mcode) in enumerate(mutants(code)):
                    rec = {"dataset": ds, "id": k, "operator": op, "line": line, "before": before,
                           "after": after, "designed_to_violate": DESIGNED_TO_VIOLATE[op]}
                    try:
                        ns = namespace(mcode)
                        mo = outputs(ns, db, ids, seeds)
                        changed = sorted({f for (s, f), v in mo.items() if frame_diff(base[(s, f)], v)})
                    except Exception as e:  # noqa: BLE001
                        rec.update(verdict="ERROR", error=f"{type(e).__name__}: {e}"[:300])
                        out.write(json.dumps(rec) + "\n")
                        continue
                    rec["changed"] = changed
                    if not changed:
                        rec["verdict"] = "EQUIVALENT"
                    else:
                        fired, errors = {}, {}
                        for f in ("select_entities", "get_features", "fit_predict"):
                            r = check_features(db, as_frame(f, ns), times, lambda t: ids_t[t],
                                               timeout=300, localize=False)
                            fired[f] = r.status
                        lab = lambda d, i, t, _ns=ns: _ns["make_label"](d, i, t)["label"]  # noqa: E731
                        r = check_task(task, "t", key, db, label_program=lab, horizon_days=H,
                                       max_times=len(seeds), timeout=300)
                        fired["make_label"] = r.status
                        rec["layers"] = fired
                        rec["verdict"] = "KILLED" if LEAK in fired.values() else "SURVIVED"
                    tl = triage.get((op, before, after))
                    if tl is not None:
                        rec["pit_violation"] = tl["pit_violation"]
                    out.write(json.dumps(rec) + "\n")
                    out.flush()
                    print(ds, k, op, rec["verdict"], rec.get("layers", ""), rec.get("pit_violation"),
                          flush=True)


if __name__ == "__main__":
    main()
