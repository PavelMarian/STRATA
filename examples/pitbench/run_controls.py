"""Run the PITBench control programs through STRATA.

    python run_controls.py --pitbench /path/to/pitbench --out controls.jsonl [ds ...]

PITBench availability maps are translated into STRATA schemas mechanically
(`map_to_schema`); the controls run unmodified. Tables load the way PITBench's
agent workspace loads them (pandas defaults, declared date columns parsed),
and entities are drawn once from the entity column with seed 0, as in
PITBench's feature-layer validation.

Expected STRATA verdict: LEAK when PITBench expects pit-check to report LEAK
or its snapshot channel to fire, CLEAN otherwise. With --snapshot-as unknown
the snapshot columns are declared unknown instead, and the expectation for
snapshot controls becomes UNCHECKABLE.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from strata import Schema, TemporalDB, check_features  # noqa: E402
from strata.sandbox import load_callable  # noqa: E402

ALL = ["olist", "f1", "pkdd99", "adventureworks", "northwind", "sakila", "movietweetings", "tpch"]


def map_to_schema(ds, amap, data_dir, snapshot_as="value_time", parse_also=None):
    """parse_also: {table: [columns]} parsed as dates without any time meaning
    (used by the map ablation, so that only the semantics differ)."""
    tables = {}
    snap = amap.get("snapshot_cols", {}) or {}
    for f in sorted(Path(data_dir).glob("*.csv")):
        t = f.stem
        spec = {"path": f.name}
        dates = list(amap.get("date_cols", {}).get(t, []))
        self_av = list(amap.get("self_availability_cols", {}).get(t, []))
        if t in amap.get("time_cols", {}):
            spec["time"] = amap["time_cols"][t]
        else:
            spec["static"] = True
        if self_av:
            spec["self_available"] = self_av
        if t in snap:
            if snapshot_as == "unknown":
                spec["unknown"] = list(snap[t])
            else:
                spec["value_time"] = dict(snap[t])
                dates += [v for v in snap[t].values() if isinstance(v, str) and v in _header(f)]
        extra = [c for c in (parse_also or {}).get(t, []) if c in _header(f)]
        spec["parse_dates"] = sorted(set(dates + self_av + extra))
        tables[t] = spec
    hints = [h for h in amap.get("key_hints", []) if h != "id"] or ["_id"]
    return {"name": ds, "root": str(Path(data_dir).resolve()), "tables": tables, "key_hints": hints}


def _header(f):
    return pd.read_csv(f, nrows=0).columns.tolist()


def expected_verdict(exp, snapshot_as):
    if exp.get("snapshot_ext"):
        return "UNCHECKABLE" if snapshot_as == "unknown" else "LEAK"
    return exp["pit_check"]["verdict"]


def outcome(expected, got):
    """A drafted schema may declare a snapshot unknown instead of dated: then
    UNCHECKABLE is also a safe answer for a leaking control (never CLEAN)."""
    return got == expected or (expected == "LEAK" and got == "UNCHECKABLE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitbench", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--snapshot-as", choices=["value_time", "unknown"], default="value_time")
    ap.add_argument("--map", default=None, help="map file name inside datasets/<ds>/ (default: manifest's)")
    ap.add_argument("--schemas", default=None,
                    help="JSONL from eval_init.py: run on these drafted schemas instead of the maps")
    ap.add_argument("datasets", nargs="*", default=ALL)
    a = ap.parse_args()
    pb = Path(a.pitbench)
    with open(a.out, "w") as out:
        for ds in a.datasets:
            man = json.load(open(pb / "datasets" / ds / "dataset.json"))
            amap = json.load(open(pb / "datasets" / ds / (a.map or man["availability_map"])))
            parse_also = None
            if a.map:   # ablation: parse the default map's date columns too
                base = json.load(open(pb / "datasets" / ds / man["availability_map"]))
                parse_also = {}
                for key in ("time_cols", "date_cols", "self_availability_cols"):
                    for t, cols in base.get(key, {}).items():
                        parse_also.setdefault(t, []).extend([cols] if isinstance(cols, str) else cols)
            if a.schemas:
                drafted = {json.loads(l)["dataset"]: json.loads(l)["schema"] for l in open(a.schemas)}
                raw = drafted[ds]
                # dates the controls parse themselves are loaded as dates, without any time meaning
                for t, cols in amap.get("date_cols", {}).items():
                    if t in raw["tables"]:
                        spec = raw["tables"][t]
                        spec["parse_dates"] = sorted(set(spec.get("parse_dates", [])) | set(cols))
                schema = Schema.from_dict(raw)
            else:
                schema = Schema.from_dict(map_to_schema(ds, amap, pb / man["data_dir"], a.snapshot_as,
                                                        parse_also))
            db = TemporalDB.load(schema)
            ent = man["entity"]
            pool = np.sort(db.tables[ent["table"]][ent["column"]].dropna().unique())
            n = min(ent["n_entities"], len(pool))
            ids = np.sort(np.random.RandomState(0).choice(pool, size=n, replace=False))
            times = [pd.Timestamp(s) for s in man["seeds"]["dev"] + man["seeds"]["held_out"]]
            for name, spec in man["controls"].items():
                prog = load_callable(f"{pb / 'datasets' / ds / 'controls' / name}:get_features")
                rep = check_features(db, prog, times, lambda t: ids, timeout=300)
                exp = expected_verdict(spec["expected"], a.snapshot_as)
                kinds = {}
                for p in rep.probes:
                    kinds.setdefault(p.kind, []).append(p.status)
                row = {"dataset": ds, "control": name, "class": spec.get("class"),
                       "expected": exp, "strata": rep.status, "agree": exp == rep.status,
                       "safe": outcome(exp, rep.status),
                       "kinds": kinds, "seconds": rep.meta["wall_seconds"],
                       "channels": sorted({c for p in rep.probes for c in p.detail.get("channels", [])}),
                       "errors": [p.detail.get("error", "")[:300] for p in rep.probes if p.status == "ERROR"]}
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(f"{ds:15s} {name:30s} expected {exp:11s} strata {rep.status:11s} "
                      f"{'ok' if row['agree'] else 'MISMATCH'} {row['channels']}", flush=True)


if __name__ == "__main__":
    main()
