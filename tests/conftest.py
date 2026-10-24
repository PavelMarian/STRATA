import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from strata import Schema, TemporalDB  # noqa: E402

SCHEMA = {
    "name": "shop",
    "tables": {
        "customers": {"time": "signup"},
        "orders": {"time": "ts", "self_available": ["delivered_at"],
                   "value_time": {"rating": "rated_at"}, "unknown": ["status"],
                   "keys": ["order_id", "customer_id"]},
        "items": {"time_from": {"table": "orders", "key": "order_id"}, "keys": ["order_id"]},
    },
    "entities": {"customer": {"table": "customers", "key": "customer_id", "created": "signup",
                              "seen_in": {"table": "orders", "column": "customer_id"}}},
}


def make_tables(seed=0, n_cust=40, n_orders=600):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2020-01-01")
    cust = pd.DataFrame({"customer_id": np.arange(n_cust),
                         "signup": start + pd.to_timedelta(rng.integers(0, 200, n_cust), "D")})
    cid = rng.integers(0, n_cust, n_orders)
    ts = cust.signup.to_numpy()[cid] + pd.to_timedelta(rng.integers(0, 300, n_orders), "D")
    orders = pd.DataFrame({
        "order_id": np.arange(n_orders), "customer_id": cid, "ts": ts,
        "amount": rng.gamma(2.0, 20.0, n_orders).round(2),
        "delivered_at": ts + pd.to_timedelta(rng.integers(2, 20, n_orders), "D"),
        "rating": rng.integers(1, 6, n_orders).astype(float),
        "rated_at": ts + pd.to_timedelta(rng.integers(10, 40, n_orders), "D"),
        "status": rng.choice(["delivered", "returned"], n_orders, p=[0.85, 0.15]),
    }).sort_values("ts").reset_index(drop=True)
    items = pd.DataFrame({"order_id": rng.integers(0, n_orders, 2 * n_orders),
                          "qty": rng.integers(1, 4, 2 * n_orders)})
    return {"customers": cust, "orders": orders, "items": items}


@pytest.fixture(scope="session")
def db():
    return TemporalDB.load(Schema.from_dict(SCHEMA), make_tables())


@pytest.fixture(scope="session")
def history():
    """A task table: customer x monthly time, label = orders in the next 30 days."""
    t = make_tables()
    o, rows = t["orders"], []
    for m in pd.date_range("2020-03-01", "2020-12-01", freq="MS"):
        live = t["customers"][t["customers"].signup <= m].customer_id
        nxt = o[(o.ts > m) & (o.ts <= m + pd.Timedelta(days=30))].customer_id
        rows.append(pd.DataFrame({"customer_id": live, "ts": m,
                                  "y": live.isin(nxt).astype(int)}))
    return pd.concat(rows, ignore_index=True)
