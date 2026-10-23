"""Check a proposed schema against the data it describes.

The checks only catch decisions the data contradicts; they cannot confirm
the meaning of a column (whether a date is planned or filled late, whether a
status has history). Findings are either "error" (the schema cannot be right
as written) or "warning" (the data makes the decision doubtful).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .infer import _read_sample
from .profile import date_lags
from .schema import Schema, _is_date

LATE_SHARE = 0.5          # a date later than the row time in most rows is late or planned
EARLY_SHARE = 0.2         # a date earlier than the row time this often doubts the row time


def check_schema(raw: dict, data_dir) -> list:
    """[{"level", "table", "column", "message"}] for a schema dict."""
    data_dir = Path(data_dir)
    out = []

    def add(level, table, column, message):
        out.append({"level": level, "table": table, "column": column, "message": message})

    try:
        Schema.from_dict(raw, base=data_dir)
    except Exception as e:  # noqa: BLE001 -- any structural error is a finding
        add("error", None, None, f"schema does not load: {e}")
        return out
    frames = {}
    for t, spec in raw["tables"].items():
        path = data_dir / spec.get("path", f"{t}.csv")
        if not path.exists():
            add("error", t, None, f"file {path.name} not found")
            continue
        frames[t] = _read_sample(path)

    for t, spec in raw["tables"].items():
        if t not in frames:
            continue
        df = frames[t]
        named = [spec.get("time")] + list(spec.get("self_available", [])) + list(spec.get("unknown", [])) \
            + list(spec.get("planned", [])) + list(spec.get("value_time", {}))
        named += [v for v in spec.get("value_time", {}).values() if isinstance(v, str) and not _is_date(v)]
        for c in [c for c in named if c]:
            if c not in df.columns:
                add("error", t, c, "column does not exist")
        if spec.get("time") in df.columns:
            rt = pd.to_datetime(df[spec["time"]], errors="coerce", format="mixed")
            if rt.notna().mean() < 0.5:
                add("error", t, spec["time"], f"row time parses as a date in only {rt.notna().mean():.0%} of rows")
            elif rt.isna().any():
                add("warning", t, spec["time"], f"{rt.isna().mean():.1%} of rows have no row time "
                                                 "and are never visible")
            lags = date_lags(data_dir, t, spec["time"], file=path_of(spec, t))
            declared = set(spec.get("self_available", [])) | set(spec.get("planned", [])) \
                | {v for v in spec.get("value_time", {}).values() if isinstance(v, str)}
            for c, lag in lags.items():
                if lag["earlier"] >= EARLY_SHARE:
                    add("warning", t, spec["time"], f"{c} is earlier than the row time in "
                                                    f"{lag['earlier']:.0%} of rows: is the row time "
                                                    "a later stamp?")
                if lag["later"] >= LATE_SHARE and c not in declared:
                    add("warning", t, c, f"later than the row time in {lag['later']:.0%} of rows but "
                                         "neither self-available nor listed as a planned date")
        if spec.get("time_from"):
            src, key = spec["time_from"]["table"], spec["time_from"]["key"]
            if src not in frames:
                add("error", t, key, f"time_from table {src} not found")
            elif key not in df.columns or key not in frames[src].columns:
                add("error", t, key, f"key {key} missing in {t} or {src}")
            else:
                parent = frames[src][key]
                if not parent.is_unique:
                    add("error", t, key, f"{key} is not unique in {src}: a row would get several times")
                cover = df[key].isin(parent).mean()
                if cover < 0.9:
                    add("warning", t, key, f"only {cover:.0%} of rows find their parent in {src} "
                                           "(sampled rows; check on the full data)")
        for col, stamp in spec.get("value_time", {}).items():
            if isinstance(stamp, str) and not _is_date(stamp) and stamp in df.columns:
                v = pd.to_datetime(df[stamp], errors="coerce", format="mixed")
                if v.notna().mean() == 0:
                    add("error", t, col, f"stamp column {stamp} never parses as a date")
    timed = {t for t, sp in raw["tables"].items() if sp.get("time")}
    links = {t: sp["time_from"]["table"] for t, sp in raw["tables"].items() if sp.get("time_from")}
    for t in links:
        seen, cur = {t}, links[t]
        while cur in links and cur not in seen:
            seen.add(cur)
            cur = links[cur]
        if cur not in timed:
            add("error", t, None, f"time_from chain from {t} ends at {cur}, which has no row time")
    for name, ent in raw.get("entities", {}).items():
        if ent.get("table") not in frames:
            add("error", None, None, f"entity {name}: table {ent.get('table')} not found")
        elif ent.get("key") not in frames[ent["table"]].columns:
            add("error", ent["table"], ent.get("key"), f"entity {name}: key column missing")
    return out


def path_of(spec, table):
    return spec.get("path", f"{table}.csv")
