"""How close does a drafted schema come to PITBench's hand-made maps?

    python eval_init.py --pitbench P                 # heuristic `strata init`
    python eval_init.py --pitbench P --llm [--model M]  # LLM schema agent via OpenRouter (OPENROUTER_API_KEY)

Per database and in total: row times that match the map (timed tables only),
late-filled columns found (recall) and wrongly declared (extra), snapshot
columns caught (declared as snapshot or unknown: both stop a silent CLEAN),
and how many data-check findings remain.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from run_controls import ALL  # noqa: E402
from strata.evidence import check_schema  # noqa: E402
from strata.infer import infer_schema  # noqa: E402


def truth(amap):
    late, snap = set(), set()
    for t, cols in amap.get("self_availability_cols", {}).items():
        late |= {(t, c) for c in cols}
    for t, spec in (amap.get("snapshot_cols") or {}).items():
        snap |= {(t, c) for c in spec}
    return dict(amap.get("time_cols", {})), late, snap


def drafted(schema):
    times, late, snap = {}, set(), set()
    for t, s in schema["tables"].items():
        if s.get("time"):
            times[t] = s["time"]
        late |= {(t, c) for c in s.get("self_available", [])}
        snap |= {(t, c) for c in list(s.get("value_time", {})) + list(s.get("unknown", []))}
    return times, late, snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitbench", required=True)
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--no-samples", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-opus-5.5", help="OpenRouter model id")
    ap.add_argument("--out")
    ap.add_argument("datasets", nargs="*", default=ALL)
    a = ap.parse_args()
    pb = Path(a.pitbench)
    rows, tot = [], dict(t_ok=0, t_n=0, l_hit=0, l_n=0, l_extra=0, s_hit=0, s_n=0, errors=0)
    for ds in a.datasets:
        man = json.load(open(pb / "datasets" / ds / "dataset.json"))
        amap = json.load(open(pb / "datasets" / ds / man["availability_map"]))
        data = pb / man["data_dir"]
        if a.llm:
            from strata.llm_init import llm_schema
            schema = llm_schema(data, samples=not a.no_samples, model=a.model,
                                log=lambda m: print(f"  {ds}: {m}", flush=True))
        else:
            schema = infer_schema(data, ds)
        t_true, l_true, s_true = truth(amap)
        t_d, l_d, s_d = drafted(schema)
        r = dict(dataset=ds,
                 t_ok=sum(t_d.get(t) == c for t, c in t_true.items()), t_n=len(t_true),
                 l_hit=len(l_true & l_d), l_n=len(l_true), l_extra=len(l_d - l_true - s_true),
                 s_hit=len(s_true & (s_d | l_d)), s_n=len(s_true),
                 errors=sum(f["level"] == "error" for f in check_schema(schema, data)))
        rows.append({**r, "schema": schema})
        for k in tot:
            tot[k] += r[k]
        print(f"{ds:15s} row time {r['t_ok']}/{r['t_n']}  late {r['l_hit']}/{r['l_n']} (+{r['l_extra']} extra)"
              f"  snapshots caught {r['s_hit']}/{r['s_n']}  data errors {r['errors']}", flush=True)
    print(f"{'total':15s} row time {tot['t_ok']}/{tot['t_n']}  late {tot['l_hit']}/{tot['l_n']} "
          f"(+{tot['l_extra']} extra)  snapshots caught {tot['s_hit']}/{tot['s_n']}  data errors {tot['errors']}")
    if a.out:
        with open(a.out, "w") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")


if __name__ == "__main__":
    main()
