"""Output comparison with an explicit tolerance."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _col_equal(x: pd.Series, y: pd.Series, atol: float) -> bool:
    if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
        xv, yv = x.to_numpy(dtype="float64"), y.to_numpy(dtype="float64")
        both = np.isnan(xv) & np.isnan(yv)
        one = np.isnan(xv) ^ np.isnan(yv)
        if one.any():
            return False
        return bool(np.all(np.where(both, 0.0, np.abs(xv - yv)) <= atol))
    xs = x.astype(object).where(x.notna(), None)
    ys = y.astype(object).where(y.notna(), None)
    return xs.equals(ys)


def frame_diff(a, b, atol=1e-9):
    """Columns that differ between two outputs; ["<shape>"] if they are not
    comparable at all; [] if equal. Rows are aligned by index."""
    if a is None or b is None:
        return [] if a is b else ["<none>"]
    if isinstance(a, pd.Series):
        a = a.to_frame()
    if isinstance(b, pd.Series):
        b = b.to_frame()
    if not isinstance(a, pd.DataFrame) or not isinstance(b, pd.DataFrame):
        a, b = pd.DataFrame(np.asarray(a)), pd.DataFrame(np.asarray(b))
    if a.shape != b.shape or list(a.columns) != list(b.columns):
        return ["<shape>"]
    if not a.index.equals(b.index):
        if set(a.index) != set(b.index):
            return ["<index>"]
        b = b.reindex(a.index)
    return [c for c in a.columns if not _col_equal(a[c], b[c], atol)]


def differing_rows(a, b, col, atol=1e-9, limit=3):
    """A few index labels where column `col` differs: the witness entities."""
    if isinstance(a, pd.Series):
        a, b = a.to_frame(), b.to_frame()
    b = b.reindex(a.index)
    x, y = a[col], b[col]
    out = []
    for idx in a.index:
        if not _col_equal(x.loc[[idx]], y.loc[[idx]], atol):
            out.append({"row": _plain(idx), "full": _plain(x.loc[idx]), "at_t": _plain(y.loc[idx])})
            if len(out) >= limit:
                break
    return out


def _plain(v):
    if isinstance(v, (np.generic,)):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return str(v)
    if isinstance(v, float) and np.isnan(v):
        return None
    return v
