"""Summaries of the PITBench runs: controls and mutants.

    python summarize.py controls controls.jsonl [...]
    python summarize.py mutants mut.jsonl [...]
"""
import collections
import json
import sys


def load(files):
    return [json.loads(l) for f in files for l in open(f)]


def controls(rows):
    print(f"controls: {sum(r['agree'] for r in rows)}/{len(rows)} agree")
    by = collections.Counter((r["class"] or "correct", r["strata"]) for r in rows)
    for k, v in sorted(by.items()):
        print(f"  {k[0]:18s} {k[1]:11s} {v}")
    for r in rows:
        if not r["agree"]:
            print("  MISMATCH", r["dataset"], r["control"], r["expected"], r["strata"], r["errors"][:1])


def truth(r):
    if "pit_violation" in r:
        return r["pit_violation"]
    return r["designed_to_violate"]          # True / False / None (needs triage)


def mutants(rows):
    live = [r for r in rows if r["verdict"] in ("KILLED", "SURVIVED")]
    print(f"mutants: {len(rows)} total, {len(live)} live, "
          f"{sum(r['verdict'] == 'EQUIVALENT' for r in rows)} equivalent, "
          f"{sum(r['verdict'] == 'ERROR' for r in rows)} error")
    print("dataset          live  viol killed  non-viol killed  untriaged")
    tot = collections.Counter()
    for ds in dict.fromkeys(r["dataset"] for r in rows):
        rs = [r for r in live if r["dataset"] == ds]
        v = [r for r in rs if truth(r) is True]
        n = [r for r in rs if truth(r) is False]
        u = [r for r in rs if truth(r) is None]
        c = dict(live=len(rs), v=len(v), vk=sum(r["verdict"] == "KILLED" for r in v),
                 n=len(n), nk=sum(r["verdict"] == "KILLED" for r in n), u=len(u))
        tot.update(c)
        print(f"{ds:16s} {c['live']:4d}  {c['vk']:3d}/{c['v']:<3d}       {c['nk']:3d}/{c['n']:<3d}"
              f"          {c['u']}")
    print(f"{'total':16s} {tot['live']:4d}  {tot['vk']:3d}/{tot['v']:<3d}       {tot['nk']:3d}/{tot['n']:<3d}"
          f"          {tot['u']}")
    print("per operator (live): killed / live")
    for op in dict.fromkeys(r["operator"] for r in rows):
        rs = [r for r in live if r["operator"] == op]
        print(f"  {op:17s} {sum(r['verdict'] == 'KILLED' for r in rs)}/{len(rs)}")
    print("layers that fired on killed violations:",
          collections.Counter(k for r in live if r["verdict"] == "KILLED" and truth(r)
                              for k, v in r["layers"].items() if v == "LEAK"))
    for r in live:
        if (truth(r) is True and r["verdict"] == "SURVIVED") or (truth(r) is False and r["verdict"] == "KILLED"):
            print("  MISS" if truth(r) else "  FALSE ALARM", r["dataset"], r["id"], r["operator"],
                  r["before"], "->", r["after"], r["layers"])
        if truth(r) is None:
            print("  UNTRIAGED", r["dataset"], r["id"], r["operator"], r["before"], "->", r["after"],
                  r["verdict"])


if __name__ == "__main__":
    kind, files = sys.argv[1], sys.argv[2:]
    (controls if kind == "controls" else mutants)(load(files))
