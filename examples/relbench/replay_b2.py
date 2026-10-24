"""Replay the B2 agent corpus (9 programs x 3 RelBench tasks) through STRATA.

    python replay_b2.py --corpus .../b2_corpus --tasks .../b2_replay --out b2_strata.jsonl

Each program is an agent-written script with its own CLI. STRATA treats it as
a black box: the model layer replays it on history up to a query time and on
the same history with later rows; the agent layer replays it on original and
anonymised identities.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from strata import Runner, check_agent, check_history  # noqa: E402

TASKS = {  # RelBench task -> (time, entity, target, label horizon in days)
    "rel-f1/driver-dnf": ("date", "driverId", "did_not_finish", 30),
    "rel-f1/driver-top3": ("date", "driverId", "qualifying", 30),
    "rel-event/user-ignore": ("timestamp", "user", "target", 7),
}
CMD = ("{python} {solution} --task-dir {{task_dir}} --time-col {{time_col}} "
       "--entity-col {{entity_col}} --target-col {{target_col}} --split {{split}} --out {{out}}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--tasks", required=True, help="directory with <db>/<task>/full/{train,val}.parquet")
    ap.add_argument("--out", required=True)
    ap.add_argument("--layers", default="model,agent")
    a = ap.parse_args()
    layers = a.layers.split(",")
    with open(a.out, "w") as f:
        for sol in sorted(Path(a.corpus).glob("*/run*/solution.py")):
            agent, run = sol.parts[-3], sol.parts[-2]
            for task, (tc, ec, yc, h) in TASKS.items():
                d = Path(a.tasks) / task / "full"
                train, query = pd.read_parquet(d / "train.parquet"), pd.read_parquet(d / "val.parquet")
                history = pd.concat([train, query], ignore_index=True)
                t = pd.to_datetime(query[tc]).iloc[0]
                runner = Runner(cmd=CMD.format(python=sys.executable, solution=sol),
                                pred_col="prediction", cols=dict(time_col=tc, entity_col=ec,
                                                                 target_col=yc), timeout=600)
                row = {"agent": agent, "run": run, "task": task}
                if "model" in layers:
                    rep = check_history("model", runner, history, tc, ec, yc, horizon_days=h,
                                        query_times=[t])
                    row["model"] = rep.status
                    row["model_detail"] = [p.detail for p in rep.probes]
                if "agent" in layers:
                    past = history[pd.to_datetime(history[tc]) + pd.Timedelta(days=h) <= t]
                    rep = check_agent(runner, past, query, ec, tc, yc)
                    row["agent_layer"] = rep.status
                    row["agent_detail"] = [p.detail for p in rep.probes]
                f.write(json.dumps(row, default=str) + "\n")
                f.flush()
                print(agent, run, task, row.get("model"), row.get("agent_layer"), flush=True)


if __name__ == "__main__":
    main()
