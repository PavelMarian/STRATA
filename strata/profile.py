"""A compact, deterministic description of a data directory.

Used twice: as the input the LLM schema agent reads, and as the evidence its
proposals are checked against. Nothing here is a guess; it is what the files
contain.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .infer import _date_columns, _read_sample

MAX_SAMPLES = 3
MAX_SAMPLE_LEN = 40


def _samples(s):
    vals = s.dropna().astype(str).unique()[:MAX_SAMPLES]
    return [v[:MAX_SAMPLE_LEN] for v in vals]


def profile(data_dir, samples=True):
    """{table: {"file", "rows_sampled", "columns": {col: {...}}}} for every CSV/Parquet file."""
    data_dir = Path(data_dir)
    out = {}
    for f in sorted([*data_dir.glob("*.csv"), *data_dir.glob("*.parquet")]):
        df = _read_sample(f)
        dates = set(_date_columns(df))
        cols = {}
        for c in df.columns:
            s = df[c]
            info = {"dtype": "date" if c in dates else str(s.dtype),
                    "null_share": round(float(s.isna().mean()), 3),
                    "unique": bool(s.is_unique)}
            if c in dates:
                d = pd.to_datetime(s, errors="coerce", format="mixed")
                info["min"], info["max"] = str(d.min()), str(d.max())
                if (d.dropna() == d.dropna().dt.normalize()).all():
                    info["midnight_only"] = True
            elif pd.api.types.is_numeric_dtype(s):
                info["min"], info["max"] = _num(s.min()), _num(s.max())
            elif samples:
                info["n_distinct"] = int(s.nunique())
                info["samples"] = _samples(s)
            cols[c] = info
        out[f.stem] = {"file": f.name, "rows_sampled": int(len(df)), "columns": cols}
    return out


def _num(v):
    return None if pd.isna(v) else (v.item() if isinstance(v, np.generic) else v)


def date_lags(data_dir, table, row_time, file=None):
    """For every other date column of `table`: share of rows whose value is
    later than the row time. A late-filled or planned date sits mostly after
    it; a date that is usually earlier than the row time suggests the row
    time is the wrong column."""
    data_dir = Path(data_dir)
    f = data_dir / file if file else next(p for p in [*data_dir.glob(f"{table}.csv"),
                                                      *data_dir.glob(f"{table}.parquet")])
    df = _read_sample(f)
    rt = pd.to_datetime(df[row_time], errors="coerce", format="mixed")
    out = {}
    for c in _date_columns(df):
        if c == row_time:
            continue
        v = pd.to_datetime(df[c], errors="coerce", format="mixed")
        both = rt.notna() & v.notna()
        if both.sum() == 0:
            continue
        out[c] = {"later": round(float((v[both] > rt[both]).mean()), 3),
                  "earlier": round(float((v[both] < rt[both]).mean()), 3),
                  "missing": round(float(v.isna().mean()), 3)}
    return out
