"""Clean and leaking programs for every layer, over the synthetic shop database."""
import numpy as np
import pandas as pd


# ---------------------------------------------------------------- features --

def feat_clean(db, ids, t):
    o = db["orders"]
    o = o[o.ts <= t]
    g = o.groupby("customer_id")
    return pd.DataFrame({"n": g.size(), "amount": g.amount.sum()}).reindex(ids).fillna(0)


def feat_rows(db, ids, t):
    """Forgets the time filter."""
    g = db["orders"].groupby("customer_id")
    return pd.DataFrame({"n": g.size()}).reindex(ids).fillna(0)


def feat_rating(db, ids, t):
    """Filters rows correctly, but the rating arrives after the order."""
    o = db["orders"]
    o = o[o.ts <= t]
    return o.groupby("customer_id").rating.mean().rename("rating").to_frame().reindex(ids)


def feat_delivery(db, ids, t):
    """Delivery time of past orders: the delivery date may still be in the future."""
    o = db["orders"]
    o = o[o.ts <= t]
    days = (o.delivered_at - o.ts).dt.days
    return days.groupby(o.customer_id).mean().rename("ship_days").to_frame().reindex(ids)


def feat_items_future(db, ids, t):
    """Items inherit time from orders; reading them without a cut leaks."""
    it = db["items"].merge(db["orders"][["order_id", "customer_id"]], on="order_id")
    return it.groupby("customer_id").qty.sum().rename("qty").to_frame().reindex(ids).fillna(0)


def feat_status(db, ids, t):
    """Time filter is right, but status has no history: availability unknown."""
    o = db["orders"]
    o = o[o.ts <= t]
    return (o.status == "returned").groupby(o.customer_id).mean().rename("ret").to_frame().reindex(ids)


# -------------------------------------------------------------------- task --

def label_clean(db, ids, t, h=30):
    o = db["orders"]
    w = o[(o.ts > t) & (o.ts <= t + pd.Timedelta(days=h))]
    return pd.Series(pd.Index(ids).isin(w.customer_id).astype(int), index=ids, name="y")


def label_open_ended(db, ids, t):
    """Any future order counts, not just the next 30 days."""
    o = db["orders"]
    return pd.Series(pd.Index(ids).isin(o[o.ts > t].customer_id).astype(int), index=ids, name="y")


# ------------------------------------------------------------- model / ICL --

def model_clean(history, query):
    t = query.ts.min()
    h = history[history.ts < t]
    rate = h.groupby("customer_id").y.mean()
    return query.customer_id.map(rate).fillna(h.y.mean()).to_numpy()


def model_leaky(history, query):
    rate = history.groupby("customer_id").y.mean()
    return query.customer_id.map(rate).fillna(history.y.mean()).to_numpy()


def icl_clean(pool, query, k=5):
    t = query.ts.min()
    p = pool[pool.ts < t]
    return np.array([p.tail(k).y.mean()] * len(query))


def icl_leaky(pool, query, k=5):
    """Picks the k most recent examples -- which include examples after t."""
    return np.array([pool.sort_values("ts").tail(k).y.mean()] * len(query))


# ------------------------------------------------------------------- agent --

KNOWN = {3: 0.99, 7: 0.98, 11: 0.97}       # "recalled" outcomes for famous entities


def agent_clean(history, query):
    rate = history.groupby("customer_id").y.mean()
    return query.customer_id.map(rate).fillna(0.5).to_numpy()


def agent_recall(history, query):
    base = agent_clean(history, query)
    known = query.customer_id.map(KNOWN)
    return np.where(known.notna(), known, base)
