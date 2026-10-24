"""Draft an availability schema for an unknown database.

The draft is a starting point for the agent or the analyst, never a verdict:
every decision it makes is listed under "_review" and must be confirmed. The
heuristics are deliberately simple and conservative:

  * the row time of a table is its earliest date column (a row exists when its
    first stamp is written; later stamps are filled in afterwards);
  * every other date column is self-available (known at its own value), except
    planned dates (estimated, limit, due, ...), which are written with the row;
  * a table without dates inherits time through a key it shares with a timed
    table, otherwise it is static;
  * text columns named like a status or state are mutable without history and
    are marked unknown.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

TIME_HINTS = ("time", "date", "timestamp", "created", "_at", "ts")
MUTABLE_HINTS = ("status", "state", "stage", "flag")
# dates that state a plan or a promise are written together with the row
PLANNED_HINTS = ("estimat", "limit", "due", "expected", "deadline", "planned", "scheduled")
SAMPLE_ROWS = 20000


def _read_sample(path: Path):
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
        return df.head(SAMPLE_ROWS)
    return pd.read_csv(path, nrows=SAMPLE_ROWS)


def _date_columns(df):
    out = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            out.append(c)
            continue
        if (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)) \
                and any(h in c.lower() for h in TIME_HINTS):
            parsed = pd.to_datetime(s.dropna().head(500), errors="coerce", format="mixed")
            if len(parsed) and parsed.notna().mean() > 0.95:
                out.append(c)
    return out


def _is_key(c):
    c = c.lower()
    return c == "id" or c.endswith("_id") or c.endswith("id")


def infer_schema(data_dir, name=None):
    data_dir = Path(data_dir)
    files = sorted([*data_dir.glob("*.csv"), *data_dir.glob("*.parquet")])
    if not files:
        raise ValueError(f"no .csv or .parquet files in {data_dir}")
    review, tables, frames, dates = [], {}, {}, {}
    for f in files:
        tname = f.stem
        df = _read_sample(f)
        frames[tname], dates[tname] = df, _date_columns(df)

    for tname, df in frames.items():
        f = next(x for x in files if x.stem == tname)
        dcols = dates[tname]
        spec = {"path": f.name}
        planned = [c for c in dcols if any(h in c.lower() for h in PLANNED_HINTS)]
        actual = [c for c in dcols if c not in planned]
        if dcols:
            spec["parse_dates"] = dcols
        if actual:
            med = {c: pd.to_datetime(df[c], errors="coerce", format="mixed").median() for c in actual}
            row_time = min((c for c in actual if pd.notna(med[c])), key=lambda c: med[c])
            spec["time"] = row_time
            others = [c for c in actual if c != row_time]
            if others:
                spec["self_available"] = others
            if planned:
                spec["planned"] = planned
            review.append(f"{tname}: row time = {row_time} (earliest date column); "
                          f"self-available = {others or 'none'}"
                          + (f"; planned dates known with the row = {planned}" if planned else ""))
        elif planned:
            spec["planned"] = planned
            review.append(f"{tname}: only planned dates {planned}; treated as known with the row")
        unknown = [c for c in df.columns if any(h in c.lower() for h in MUTABLE_HINTS)
                   and not pd.api.types.is_numeric_dtype(df[c])]
        if unknown:
            spec["unknown"] = unknown
            review.append(f"{tname}: {unknown} look mutable without history -> unknown")
        spec["keys"] = [c for c in df.columns if _is_key(c)]
        tables[tname] = spec

    timed = {t: s for t, s in tables.items() if "time" in s}
    for tname, spec in tables.items():
        if "time" in spec or "time_from" in spec:
            continue
        link = None
        for c in spec["keys"]:
            for src, sspec in timed.items():
                if c in frames[src].columns and frames[src][c].is_unique:
                    link = {"table": src, "key": c}
                    break
            if link:
                break
        if link:
            spec["time_from"] = link
            review.append(f"{tname}: no date column; inherits row time from {link['table']} "
                          f"via {link['key']}")
        else:
            spec["static"] = True
            review.append(f"{tname}: no date column and no link -> static reference table")

    entities = {}
    for tname, spec in tables.items():
        df = frames[tname]
        uniq = [c for c in spec["keys"] if df[c].is_unique]
        if uniq:
            key = uniq[0]
            ent = {"table": tname, "key": key, "created": spec.get("time")}
            entities[tname] = ent
            if spec.get("static"):
                review.append(f"entity {tname}.{key}: no creation time -> population check "
                              "will be UNCHECKABLE")
    return {"name": name or data_dir.name, "root": str(data_dir.resolve()),
            "tables": tables, "entities": entities, "_review": review}


def write_draft(data_dir, out, name=None):
    draft = infer_schema(data_dir, name)
    Path(out).write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
    return draft
