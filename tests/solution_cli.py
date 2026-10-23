"""A script with its own CLI, like an agent-written solution."""
import argparse

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--task-dir")
ap.add_argument("--split")
ap.add_argument("--out")
ap.add_argument("--leaky", action="store_true")
a = ap.parse_args()

train = pd.read_parquet(f"{a.task_dir}/train.parquet")
query = pd.read_parquet(f"{a.task_dir}/{a.split}.parquet")
if not a.leaky:
    train = train[train.ts < query.ts.min()]
rate = train.groupby("customer_id").y.mean()
pd.DataFrame({"customer_id": query.customer_id,
              "score": query.customer_id.map(rate).fillna(train.y.mean())}).to_csv(a.out, index=False)
