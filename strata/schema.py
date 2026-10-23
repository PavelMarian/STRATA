"""Availability schema and the temporal database built from it.

The schema is the only place where a concrete database enters STRATA. It says,
for every table, when a row becomes known and when each late-filled column
becomes known. Everything else in the tool is database-independent.

Schema (JSON):

    {
      "name": "olist",
      "root": "../../PITFALL_olist_data",          # optional, relative to the schema file
      "tables": {
        "orders": {
          "path": "olist_orders_dataset.csv",
          "time": "order_purchase_timestamp",        # row time
          "parse_dates": ["order_purchase_timestamp", "order_delivered_customer_date"],
          "self_available": ["order_delivered_customer_date"],   # known at its own value
          "planned": ["order_estimated_delivery_date"],          # a plan, written with the row
          "value_time": {"review_score": "review_creation_date"},# column -> its own stamp
          # a stamp is a column, a fixed date ("1995-06-17"), or null: the stored
          # value is its end-of-data state (a snapshot) and is never known before
          "unknown": ["order_status"],               # mutable, no history
          "keys": ["order_id", "customer_id"]
        },
        "order_items": {
          "path": "olist_order_items_dataset.csv",
          "time_from": {"table": "orders", "key": "order_id", "column": "ts"}
        },
        "products": {"path": "olist_products_dataset.csv", "static": true}
      },
      "entities": {
        "product": {"table": "products", "key": "product_id", "created": null}
      }
    }

"key_hints" (top level, optional) overrides the suffixes that mark key columns,
which are never perturbed.

A table is exactly one of: timed ("time"), inheriting its time through a key
("time_from"), or static ("static": true, a reference table without time).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

KEY_HINTS = ("_id", "id", "key", "zip", "prefix")


@dataclass
class TableSpec:
    name: str
    path: str | None = None
    time: str | None = None
    time_from: dict | None = None
    static: bool = False
    parse_dates: list = field(default_factory=list)
    self_available: list = field(default_factory=list)
    planned: list = field(default_factory=list)      # dates written with the row (estimates, due dates)
    value_time: dict = field(default_factory=dict)
    unknown: list = field(default_factory=list)
    keys: list | None = None
    key_hints: tuple = KEY_HINTS

    def is_key(self, col):
        if self.keys is not None:
            return col in self.keys
        c = col.lower()
        return c == "id" or any(c.endswith(h) for h in self.key_hints)

    def stamp_columns(self):
        """value_time stamps that are columns of this table (not dates or null)."""
        return {v for v in self.value_time.values() if isinstance(v, str) and not _is_date(v)}


@dataclass
class EntitySpec:
    name: str
    table: str
    key: str
    created: str | None = None        # column with the entity's creation time
    seen_in: dict | None = None       # {"table": t, "column": c}: sample only entities active by t


@dataclass
class Schema:
    name: str
    tables: dict
    entities: dict
    root: Path

    @classmethod
    def load(cls, path):
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw, base=path.parent)

    @classmethod
    def from_dict(cls, raw, base="."):
        base = Path(base)
        root = raw.get("root")
        if not root:
            root = base.resolve()                 # tables sit next to the schema file
        else:
            root = Path(os.path.expandvars(root))
            if not root.is_absolute():
                root = (base / root).resolve()
        tables = {}
        hints = tuple(raw.get("key_hints", KEY_HINTS))
        for name, t in raw["tables"].items():
            spec = TableSpec(name=name, key_hints=hints, **t)
            kinds = [spec.time is not None, spec.time_from is not None, spec.static]
            if sum(kinds) != 1:
                raise ValueError(f"table {name}: give exactly one of time / time_from / static")
            tables[name] = spec
        entities = {n: EntitySpec(name=n, **e) for n, e in raw.get("entities", {}).items()}
        return cls(raw.get("name", "db"), tables, entities, root)


def _is_date(v):
    return isinstance(v, str) and len(v) >= 8 and v[:4].isdigit() and v[4] == "-"


def value_stamp(df, stamp):
    """When each stored value becomes valid: a column, a fixed date, or NaT
    (never before the end of the data)."""
    if stamp is None:
        return pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    if _is_date(stamp):
        return pd.Series(pd.Timestamp(stamp), index=df.index)
    return pd.to_datetime(df[stamp], errors="coerce")


def _read(path, parse_dates):
    p = str(path)
    if p.endswith(".parquet"):
        df = pd.read_parquet(p)
        for c in parse_dates:
            df[c] = pd.to_datetime(df[c])
        return df
    return pd.read_csv(p, parse_dates=parse_dates or False)


class TemporalDB:
    """Tables plus the availability relation of a schema.

    `tables` is what the program under test sees. Row times are kept apart from
    the tables (unless a schema asks to materialise an inherited time as a
    column), so the tool adds nothing the program could read by accident.
    """

    def __init__(self, schema: Schema, tables: dict, row_time: dict):
        self.schema = schema
        self.tables = tables
        self.row_time = row_time          # table -> pd.Series of row times, or None

    # ------------------------------------------------------------ loading --
    @classmethod
    def load(cls, schema: Schema, tables: dict | None = None):
        tables = dict(tables) if tables is not None else {}
        for name, spec in schema.tables.items():
            if name not in tables:
                if spec.path is None:
                    raise ValueError(f"table {name}: no path and no frame given")
                dates = list(dict.fromkeys(list(spec.parse_dates) + list(spec.self_available)
                                           + list(spec.planned)))
                if spec.time and spec.time not in dates:
                    dates.append(spec.time)
                tables[name] = _read(schema.root / spec.path, dates)
        row_time = {}
        for name, spec in schema.tables.items():
            df = tables[name]
            if spec.time:
                row_time[name] = pd.to_datetime(df[spec.time])
        # inherited times may chain (client -> disp -> account): resolve until fixed
        pending = [n for n, sp in schema.tables.items() if sp.time_from]
        while pending:
            progressed = False
            for name in list(pending):
                spec = schema.tables[name]
                src, key = spec.time_from["table"], spec.time_from["key"]
                if src not in row_time:
                    continue
                stamps = pd.Series(row_time[src].values, index=tables[src][key].values)
                stamps = stamps[~stamps.index.duplicated()]
                t = tables[name][key].map(stamps)
                df = tables[name]
                keep = t.notna()
                if not keep.all():
                    df, t = df[keep], t[keep]
                col = spec.time_from.get("column")
                if col:
                    df = df.copy()
                    df[col] = t
                tables[name] = df
                row_time[name] = t
                pending.remove(name)
                progressed = True
            if not progressed:
                raise ValueError(f"tables {pending}: time_from leads to no timed table (cycle or static parent)")
        for name, spec in schema.tables.items():
            if spec.static:
                row_time[name] = None
        return cls(schema, tables, row_time)

    # ------------------------------------------------------------ helpers --
    def channels(self):
        """Ways the future can reach a program: a row of a timed table, or a
        late-filled value. Used to localise a leak."""
        ch = []
        for name, spec in self.schema.tables.items():
            if self.row_time.get(name) is not None:
                ch.append(("row", name))
            ch += [("val", name, c) for c in spec.value_time]
            ch += [("self", name, c) for c in spec.self_available]
        return ch

    def time_range(self):
        stamps = [s for s in self.row_time.values() if s is not None and len(s)]
        lo = min(s.min() for s in stamps)
        hi = max(s.max() for s in stamps)
        return lo, hi

    def horizon(self):
        """Latest stamp anywhere in the data, row or value."""
        hi = self.time_range()[1]
        for name, spec in self.schema.tables.items():
            df = self.tables[name]
            for c in list(spec.self_available) + sorted(spec.stamp_columns()):
                if c in df.columns:
                    m = pd.to_datetime(df[c]).max()
                    if pd.notna(m):
                        hi = max(hi, m)
        return hi

    def _with(self, tables, row_time):
        return TemporalDB(self.schema, tables, row_time)

    # ------------------------------------------------------ interventions --
    def truncate(self, t, only=None):
        """State of the database at time t: rows that did not exist yet are
        removed, values that were not filled in yet are blanked. `only` limits
        the cut to a set of channels (for localisation)."""
        t = pd.Timestamp(t)
        tables, row_time = {}, {}
        for name, spec in self.schema.tables.items():
            df, rt = self.tables[name], self.row_time.get(name)
            if rt is not None and (only is None or ("row", name) in only):
                keep = (rt <= t).to_numpy()
                df, rt = df[keep], rt[keep]
            df = df.copy()
            for col, tcol in spec.value_time.items():
                if only is not None and ("val", name, col) not in only:
                    continue
                mask = ~(value_stamp(df, tcol) <= t)
                df.loc[mask, col] = np.nan
                if tcol in spec.stamp_columns() and tcol not in spec.self_available:
                    df.loc[mask, tcol] = pd.NaT
            for col in spec.self_available:
                if only is not None and ("self", name, col) not in only:
                    continue
                v = pd.to_datetime(df[col])
                df.loc[v > t, col] = pd.NaT
            tables[name] = df
            row_time[name] = rt
        return self._with(tables, row_time)

    def canary(self, t, num_shift=7919.0, sentinel="__strata_canary__", margin_days=3650):
        """Same availability at t, different future: every value the cut would
        remove is overwritten. A program that is PIT-correct cannot tell this
        database from the original. Keys and row times are never touched."""
        t = pd.Timestamp(t)
        far = self.horizon() + pd.Timedelta(days=margin_days)
        tables = {}
        for name, spec in self.schema.tables.items():
            df, rt = self.tables[name].copy(), self.row_time.get(name)
            protected = {spec.time} | spec.stamp_columns() - set(spec.self_available)
            if spec.time_from and spec.time_from.get("column"):
                protected.add(spec.time_from["column"])
            future = (rt > t).to_numpy() if rt is not None else np.zeros(len(df), bool)
            for col in df.columns:
                if col in protected or spec.is_key(col) or col in spec.unknown:
                    continue
                if col in spec.self_available:
                    v = pd.to_datetime(df[col])
                    df.loc[(v > t) | v.isna(), col] = far
                    continue
                mask = future.copy()
                if col in spec.value_time:
                    mask |= ~(value_stamp(df, spec.value_time[col]) <= t).to_numpy()
                if mask.any():
                    df[col] = _perturb(df[col], mask, num_shift, sentinel, far)
            tables[name] = df
        return self._with(tables, dict(self.row_time))

    def probe_unknown(self, seed=0, sentinel="__strata_unknown__"):
        """Database with every column of unknown availability perturbed. A
        changed output means the program reads such a column: its verdict
        cannot be CLEAN, only UNCHECKABLE."""
        rng = np.random.default_rng(seed)
        tables = {}
        for name, spec in self.schema.tables.items():
            df = self.tables[name]
            if spec.unknown:
                df = df.copy()
                for col in spec.unknown:
                    if col in df.columns:
                        mask = np.ones(len(df), bool)
                        df[col] = _perturb(df[col], mask, 7919.0, sentinel, None, rng)
            tables[name] = df
        return self._with(tables, dict(self.row_time))

    def nudge_past(self, t, eps=pd.Timedelta(microseconds=1)):
        """Rows stamped exactly at t moved to t - eps. History is unchanged for
        anything that reads rows <= t; an outcome window that is closed at t
        ([t, t+h] instead of (t, t+h]) loses them."""
        t = pd.Timestamp(t)
        tables, row_time = {}, {}
        for name, spec in self.schema.tables.items():
            df, rt = self.tables[name], self.row_time.get(name)
            if rt is not None and (rt == t).any():
                df = df.copy()
                at = (rt == t).to_numpy()
                col = spec.time or (spec.time_from or {}).get("column")
                if col:
                    df.loc[at, col] = t - eps
                rt = rt.where(~at, t - eps)
            tables[name] = df
            row_time[name] = rt
        return self._with(tables, row_time)

    def entities_at(self, entity: str, t, n=15, seed=0):
        """A reproducible sample of entities that exist (or were active) at t."""
        spec = self.schema.entities[entity]
        t = pd.Timestamp(t)
        if spec.seen_in:
            tab, col = spec.seen_in["table"], spec.seen_in["column"]
            rt = self.row_time[tab]
            ids = self.tables[tab].loc[(rt <= t).to_numpy(), col]
        else:
            df = self.tables[spec.table]
            ids = df[spec.key]
            if spec.created:
                ids = ids[(pd.to_datetime(df[spec.created]) <= t).to_numpy()]
        ids = np.sort(pd.unique(ids.dropna()))
        if len(ids) > n:
            ids = np.sort(np.random.RandomState(seed).choice(ids, size=n, replace=False))
        return ids

    def has_unknown(self):
        return any(spec.unknown for spec in self.schema.tables.values())

    def as_dict(self):
        return dict(self.tables)


def _perturb(s, mask, num_shift, sentinel, far, rng=None):
    s = s.copy()
    if pd.api.types.is_bool_dtype(s):
        s = s.astype(object)
        s[mask] = ~s[mask].astype(bool)
    elif pd.api.types.is_datetime64_any_dtype(s):
        s[mask] = far if far is not None else s[mask] + pd.Timedelta(days=3650)
    elif pd.api.types.is_numeric_dtype(s):
        s = s.astype("float64")
        s[mask] = s[mask] + num_shift
    elif isinstance(s.dtype, pd.CategoricalDtype):
        if sentinel not in s.cat.categories:
            s = s.cat.add_categories([sentinel])
        s[mask] = sentinel
    else:
        s = s.astype(object)
        if rng is not None:
            vals = s[mask].dropna().unique()
            if len(vals) > 1:
                s[mask] = rng.permutation(s[mask].to_numpy())
                return s
        s[mask] = sentinel
    return s
