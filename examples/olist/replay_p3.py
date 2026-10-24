"""Replay the P3 corpus (generated Olist feature programs) through STRATA.

    python replay_p3.py --shard 0 --of 4 --out p3_shard0.jsonl

Entities and times are the ones the original P3 oracle used, so the witness
verdicts are directly comparable with prestudy/p3_out/baseline/results.jsonl.
"""
import argparse
import hashlib
import json
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parents[1]))
sys.modules.setdefault("litellm", types.ModuleType("litellm"))
sys.path.insert(0, str(ROOT / "prestudy"))

import p3_baseline_run as H  # noqa: E402
from strata import Schema, TemporalDB, check_features  # noqa: E402

TIMES = [pd.Timestamp(s) for s in H.TEST_SEEDS]


def ids_at(t):
    _, prods, _ = H.labels(t)
    return np.random.RandomState(0).choice(prods, size=H.N_SAMPLE_PRODUCTS, replace=False)


def sha(r):
    """Programs are keyed by their code: (model, idx) repeats across batches."""
    return hashlib.sha256(r["code"].encode()).hexdigest()[:16]


def compile_program(code):
    ns = {"pd": pd, "np": np}
    exec(code, ns)  # noqa: S102 -- runs only inside STRATA's forked child
    return ns["get_features"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--recheck", nargs="*", default=[],
                    help="earlier outputs: re-run only programs that were not LEAK there")
    a = ap.parse_args()
    db = TemporalDB.load(Schema.load(HERE / "schema.json"))
    rows = [json.loads(l) for l in open(ROOT / "prestudy/p3_out/baseline/results.jsonl")]
    rows = [r for r in rows if r["status"] == "ok"]
    if a.recheck:
        prev = [json.loads(l) for f in a.recheck for l in open(f)]
        keep = {d["sha"] for d in prev if d.get("strata") != "LEAK"}
        rows = [r for r in rows if sha(r) in keep]
    done = set()
    if Path(a.out).exists():
        done = {d["sha"] for d in map(json.loads, open(a.out))}
    with open(a.out, "a") as f:
        for i, r in enumerate(rows):
            if i % a.of != a.shard or sha(r) in done:
                continue
            try:
                fn = compile_program(r["code"])
            except Exception as e:  # noqa: BLE001
                f.write(json.dumps({"sha": sha(r), "model": r["model"], "idx": r["idx"],
                                    "error": str(e)}) + "\n")
                continue
            rep = check_features(db, fn, TIMES, ids_at, timeout=60, localize=True)
            kinds = {}
            for p in rep.probes:
                kinds.setdefault(p.kind, []).append(p.status)
            f.write(json.dumps({"sha": sha(r), "model": r["model"], "idx": r["idx"], "p3_verdict": r["verdict"],
                                "strata": rep.status, "kinds": kinds,
                                "channels": sorted({c for p in rep.probes
                                                    for c in p.detail.get("channels", [])})}) + "\n")
            f.flush()


if __name__ == "__main__":
    main()
