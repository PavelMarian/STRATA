import json
import sys
from pathlib import Path

import pandas as pd
import pytest

import programs as P
from conftest import HERE, SCHEMA, make_tables
from strata import (CLEAN, LEAK, UNCHECKABLE, Runner, Schema, TemporalDB, check_agent,
                    check_features, check_history, check_task)
from strata.cli import main as cli_main
from strata.infer import infer_schema

TIMES = [pd.Timestamp("2020-05-01"), pd.Timestamp("2020-08-01")]


# ------------------------------------------------------------- schema / db --

def test_truncate_is_a_state_of_the_past(db):
    t = TIMES[0]
    cut = db.truncate(t)
    o = cut.tables["orders"]
    assert (o.ts <= t).all()
    assert o.loc[o.rated_at.isna(), "rating"].isna().all()
    assert not (o.delivered_at > t).any()
    assert len(cut.tables["items"]) < len(db.tables["items"])      # inherited time is cut too


def test_canary_keeps_the_past(db):
    t = TIMES[0]
    from strata.compare import frame_diff
    a = db.truncate(t).tables["orders"].sort_values("order_id").reset_index(drop=True)
    b = db.canary(t).truncate(t).tables["orders"].sort_values("order_id").reset_index(drop=True)
    assert frame_diff(a, b) == []


# ---------------------------------------------------------------- features --

@pytest.mark.parametrize("prog,expected", [
    (P.feat_clean, CLEAN), (P.feat_rows, LEAK), (P.feat_rating, LEAK),
    (P.feat_delivery, LEAK), (P.feat_items_future, LEAK), (P.feat_status, UNCHECKABLE),
])
def test_features(db, prog, expected):
    rep = check_features(db, prog, TIMES, "customer", timeout=60)
    assert rep.status == expected, rep.summary()
    if expected == LEAK:
        assert rep.witnesses


def test_features_localizes_the_channel(db):
    rep = check_features(db, P.feat_rating, TIMES[:1], "customer")
    chans = [c for p in rep.probes for c in p.detail.get("channels", [])]
    assert any("rating" in c for c in chans), chans


def test_features_from_file_spec(db):
    rep = check_features(db, f"{HERE / 'programs.py'}:feat_clean", TIMES[:1], "customer")
    assert rep.status == CLEAN


# -------------------------------------------------------------------- task --

def test_task_population(db, history):
    bad = history.copy()
    bad.loc[bad.index[:5], "ts"] = pd.Timestamp("2019-06-01")     # before signup
    assert check_task(history, "ts", "customer_id", db, "customer").status == CLEAN
    rep = check_task(bad, "ts", "customer_id", db, "customer")
    assert rep.status == LEAK and rep.witnesses


def test_task_population_uncheckable_without_creation_time(history):
    schema = json.loads(json.dumps(SCHEMA))
    schema["entities"]["customer"]["created"] = None
    db2 = TemporalDB.load(Schema.from_dict(schema), make_tables())
    assert check_task(history, "ts", "customer_id", db2, "customer").status == UNCHECKABLE


def test_task_label_horizon(db, history):
    small = history[history.ts.isin(pd.to_datetime(["2020-05-01", "2020-08-01"]))]
    ok = check_task(small, "ts", "customer_id", db, label_program=P.label_clean, horizon_days=30)
    bad = check_task(small, "ts", "customer_id", db, label_program=P.label_open_ended,
                     horizon_days=30)
    assert ok.status == CLEAN and bad.status == LEAK


def test_task_split_order(history):
    a = history[history.ts < "2020-08-01"]
    b = history[history.ts >= "2020-08-01"]
    assert check_task(history, "ts", "customer_id", splits={"train": a, "val": b}).status == CLEAN
    assert check_task(history, "ts", "customer_id", splits={"train": b, "val": a}).status == LEAK


# ------------------------------------------------------------- model / ICL --

COLS = dict(time_col="ts", entity_col="customer_id", target_col="y")


@pytest.mark.parametrize("prog,expected", [(P.model_clean, CLEAN), (P.model_leaky, LEAK)])
def test_model_callable(history, prog, expected):
    rep = check_history("model", Runner(program=prog, cols=COLS), history, "ts", "customer_id", "y")
    assert rep.status == expected, rep.summary()


@pytest.mark.parametrize("flag,expected", [("", CLEAN), (" --leaky", LEAK)])
def test_model_command(history, flag, expected):
    cmd = f"{sys.executable} {HERE / 'solution_cli.py'} --task-dir {{task_dir}} --split {{split}} --out {{out}}{flag}"
    rep = check_history("model", Runner(cmd=cmd, cols=COLS), history, "ts", "customer_id", "y")
    assert rep.status == expected, rep.summary()


@pytest.mark.parametrize("prog,expected", [(P.icl_clean, CLEAN), (P.icl_leaky, LEAK)])
def test_icl(history, prog, expected):
    rep = check_history("icl", Runner(program=prog, cols=COLS), history, "ts", "customer_id", "y")
    assert rep.status == expected, rep.summary()


def test_nondeterministic_program_is_uncheckable(history):
    import numpy as np

    def noisy(h, q):
        return np.random.default_rng().random(len(q))
    rep = check_history("model", Runner(program=noisy, cols=COLS), history, "ts", "customer_id", "y")
    assert rep.status == UNCHECKABLE


# ------------------------------------------------------------------- agent --

@pytest.mark.parametrize("prog,expected", [(P.agent_clean, CLEAN), (P.agent_recall, LEAK)])
def test_agent(history, prog, expected):
    t = pd.Timestamp("2020-10-01")
    train, query = history[history.ts < t], history[history.ts == t]
    rep = check_agent(Runner(program=prog, cols=COLS), train, query, "customer_id", "ts", "y")
    assert rep.status == expected, rep.summary()


# --------------------------------------------------------------- infer / CLI --

def test_infer_and_cli(tmp_path, history):
    t = make_tables()
    for name, df in t.items():
        df.to_csv(tmp_path / f"{name}.csv", index=False)
    draft = infer_schema(tmp_path, "shop")
    assert draft["tables"]["orders"]["time"] == "ts"
    assert set(draft["tables"]["orders"]["self_available"]) == {"delivered_at", "rated_at"}
    assert draft["tables"]["items"]["time_from"]["table"] == "orders"
    assert "status" in draft["tables"]["orders"]["unknown"]
    sp = tmp_path / "schema.json"
    sp.write_text(json.dumps(draft))
    rc = cli_main(["check", "features", "--schema", str(sp), "--entity", "customers",
                   "--program", f"{HERE / 'programs.py'}:feat_rows", "--times", "2020-06-01",
                   "--report", str(tmp_path / "r.json")])
    assert rc == 1
    assert json.loads((tmp_path / "r.json").read_text())["status"] == LEAK


def test_agent_hashed_ids_are_uncheckable(history):
    import zlib

    def hashed(h, q):
        return q.customer_id.astype(str).map(lambda v: zlib.crc32(v.encode()) % 100 / 100).to_numpy()
    t = pd.Timestamp("2020-10-01")
    train, query = history[history.ts < t], history[history.ts == t]
    rep = check_agent(Runner(program=hashed, cols=COLS), train, query, "customer_id", "ts", "y")
    assert rep.status == UNCHECKABLE, rep.summary()


def test_features_without_output_is_error(db):
    from strata import ERROR

    def nothing(tables, ids, t):
        return None
    assert check_features(db, nothing, TIMES[:1], "customer").status == ERROR


@pytest.mark.parametrize("stamp,expected", [(None, LEAK), ("2030-01-01", LEAK), ("2000-01-01", CLEAN)])
def test_snapshot_value_stamps(stamp, expected):
    """A value stored as its end-of-data state: stamp null (never known before
    the end), a fixed validity date, or a date before every tested time."""
    schema = json.loads(json.dumps(SCHEMA))
    schema["tables"]["customers"]["value_time"] = {"tier": stamp}
    tables = make_tables()
    tables["customers"]["tier"] = tables["customers"].customer_id % 3

    def tier(db, ids, t):
        c = db["customers"]
        return c[c.signup <= t].set_index("customer_id").tier.reindex(ids).to_frame()
    db2 = TemporalDB.load(Schema.from_dict(schema), tables)
    assert check_features(db2, tier, TIMES, "customer").status == expected


def test_task_label_lower_boundary(db, history):
    """Orders stamped exactly at t belong to history: a label window closed at t leaks."""
    tables = make_tables()
    t = pd.Timestamp("2020-06-01")
    tables["orders"].loc[tables["orders"].index[:20], "ts"] = t
    db2 = TemporalDB.load(Schema.from_dict(SCHEMA), tables)
    task = history[history.ts == t]

    def closed(dbt, ids, t, h=30):
        o = dbt["orders"]
        w = o[(o.ts >= t) & (o.ts <= t + pd.Timedelta(days=h))]
        return pd.Series(pd.Index(ids).isin(w.customer_id).astype(int), index=ids)
    ok = check_task(task, "ts", "customer_id", db2, label_program=P.label_clean, horizon_days=30)
    bad = check_task(task, "ts", "customer_id", db2, label_program=closed, horizon_days=30)
    assert ok.status == CLEAN and bad.status == LEAK, bad.summary()


def test_chained_time_inheritance():
    schema = json.loads(json.dumps(SCHEMA))
    schema["tables"]["lines"] = {"time_from": {"table": "items", "key": "item_id"}}
    tables = make_tables()
    tables["items"]["item_id"] = range(len(tables["items"]))
    tables["lines"] = pd.DataFrame({"item_id": [0, 1, 2]})
    db2 = TemporalDB.load(Schema.from_dict(schema), tables)
    assert db2.row_time["lines"].notna().all()


def test_schema_without_root_reads_next_to_the_file(tmp_path, monkeypatch):
    d = tmp_path / "db"
    d.mkdir()
    for name, df in make_tables().items():
        df.to_csv(d / f"{name}.csv", index=False)
    schema = json.loads(json.dumps(SCHEMA))
    for n in schema["tables"]:
        schema["tables"][n]["path"] = f"{n}.csv"
    (d / "schema.json").write_text(json.dumps(schema))
    monkeypatch.chdir(tmp_path)
    db2 = TemporalDB.load(Schema.load("db/schema.json"))        # relative path, no "root"
    assert len(db2.tables["orders"]) == len(make_tables()["orders"])
