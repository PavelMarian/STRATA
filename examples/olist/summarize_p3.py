"""Summarize the P3 replay: STRATA verdicts against the original row-level oracle."""
import collections
import json
import sys

rows = [json.loads(l) for f in sys.argv[1:] for l in open(f)]
rows = list({r["sha"]: r for r in rows}.values())   # later files override earlier ones
rows = [r for r in rows if "strata" in r]
n = len(rows)
wit = [r for r in rows if "LEAK" in r["kinds"].get("witness", [])]
can_only = [r for r in rows if r not in wit and "LEAK" in r["kinds"].get("canary", [])]
unk = [r for r in rows if r["strata"] == "UNCHECKABLE"]
p3_leak = [r for r in rows if r["p3_verdict"] == "LEAK"]
print(f"programs {n}")
print("strata status", collections.Counter(r["strata"] for r in rows))
print(f"witness LEAK {len(wit)}; canary-only LEAK {len(can_only)}")
print("p3 verdicts", collections.Counter(r["p3_verdict"] for r in rows))
print("p3 LEAK -> strata witness LEAK:", sum(r in wit for r in p3_leak), "/", len(p3_leak))
print("p3 CLEAN -> strata:", collections.Counter(
    ("witness" if r in wit else "canary" if r in can_only else r["strata"])
    for r in rows if r["p3_verdict"] == "CLEAN"))
print("strata witness LEAK but p3 CLEAN:", [(r["model"].split("/")[-1], r["idx"], r["channels"])
                                            for r in wit if r["p3_verdict"] == "CLEAN"])
print("errors", collections.Counter(s for r in rows for k, v in r["kinds"].items() for s in v if s == "ERROR"))
ch = collections.Counter(c for r in rows for c in r["channels"])
print("channels", ch)
print("leaking programs localized to reviews:",
      sum(any(c.startswith("reviews") for c in r["channels"]) for r in rows if r["strata"] == "LEAK"),
      "/", sum(r["strata"] == "LEAK" for r in rows))
