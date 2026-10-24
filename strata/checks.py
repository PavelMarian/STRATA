"""The five layer checks. Each one runs the layer twice -- on what existed at
the prediction time t and on what exists in the data now -- and compares the
layer's own output. None of them reads the program's code.

    task      task rows and labels vs. entity creation time and label horizon
    features  get_features(db, entities, t) on D vs. D|t, plus a canary on D'
    model     a training program on history up to t vs. history with later rows
    icl       a context-based predictor on a pool up to t vs. pool with later rows
    agent     an end-to-end program on original vs. anonymised identities
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .compare import differing_rows, frame_diff
from .sandbox import ProgramError, call_isolated, run_command
from .verdict import CLEAN, ERROR, LEAK, UNCHECKABLE, Probe, Report


def _ts(t):
    return str(pd.Timestamp(t))


# =============================================================== features ==

def check_features(db, program, times, entity, n_entities=15, atol=1e-9,
                   timeout=60, mem_mb=4096, localize=True, canary=True):
    """program(tables: dict[str, DataFrame], entity_ids, t) -> DataFrame by entity."""
    rep = Report("features", str(program), meta={"schema": db.schema.name, "entity": entity,
                                                 "times": [_ts(t) for t in times]})

    def run(state, ids, t):
        return call_isolated(program, (state.tables, ids, pd.Timestamp(t)), timeout, mem_mb)

    localized = False
    for t in times:
        t = pd.Timestamp(t)
        ids = entity(t) if callable(entity) else db.entities_at(entity, t, n_entities)
        try:
            full = run(db, ids, t)
            at_t = db.truncate(t)
            cut = run(at_t, ids, t)
        except ProgramError as e:
            rep.add(Probe(_ts(t), ERROR, "run", {"error": str(e)}))
            continue
        if not isinstance(full, (pd.DataFrame, pd.Series)):
            rep.add(Probe(_ts(t), ERROR, "run",
                          {"error": f"expected a DataFrame, got {type(full).__name__}"}))
            continue
        cols = frame_diff(full, cut, atol)
        detail = {"columns": cols, "n_entities": int(len(ids))}
        if cols:
            if localize and not localized and not cols[0].startswith("<"):
                detail["channels"] = _localize(db, run, ids, t, full, atol)
                localized = True
            for c in cols[:3]:
                if not c.startswith("<"):
                    for w in differing_rows(full, cut, c, atol, limit=1):
                        rep.witnesses.append({"time": _ts(t), "column": c, **w,
                                              "channels": detail.get("channels", [])})
        rep.add(Probe(_ts(t), LEAK if cols else CLEAN, "witness", detail))

        if canary:
            try:
                can = run(db.canary(t), ids, t)
                ccols = frame_diff(full, can, atol)
                rep.add(Probe(_ts(t), LEAK if ccols else CLEAN, "canary", {"columns": ccols}))
            except ProgramError as e:
                rep.add(Probe(_ts(t), ERROR, "canary", {"error": str(e)}))

        if db.has_unknown() and not cols:
            try:
                unk = run(at_t.probe_unknown(), ids, t)
                ucols = frame_diff(cut, unk, atol)
                rep.add(Probe(_ts(t), UNCHECKABLE if ucols else CLEAN, "unknown",
                              {"columns": ucols}))
            except ProgramError as e:
                rep.add(Probe(_ts(t), ERROR, "unknown", {"error": str(e)}))
    if any(p.kind == "unknown" and p.status == UNCHECKABLE for p in rep.probes):
        rep.notes.append("output depends on a column whose availability is unknown")
    return rep.finish()


def _localize(db, run, ids, t, full, atol):
    """Channels that alone carry the future into the output."""
    found = []
    for ch in db.channels():
        try:
            out = run(db.truncate(t, only=frozenset([ch])), ids, t)
        except ProgramError:
            continue
        if frame_diff(full, out, atol):
            found.append(".".join(ch[1:]) + ("" if ch[0] == "row" else f" ({ch[0]})"))
    return found


# =================================================================== task ==

def check_task(task: pd.DataFrame, time_col, entity_col, db=None, entity=None,
               splits: dict | None = None, label_program=None, horizon_days=None,
               max_times=5, timeout=120, mem_mb=4096, atol=1e-9):
    rep = Report("task", entity or entity_col, meta={"rows": int(len(task))})
    task = task.copy()
    task[time_col] = pd.to_datetime(task[time_col])

    # 1. split order
    if splits:
        names = list(splits)
        for a, b in zip(names, names[1:]):
            amax = pd.to_datetime(splits[a][time_col]).max()
            bmin = pd.to_datetime(splits[b][time_col]).min()
            ok = amax <= bmin
            rep.add(Probe(f"{a}->{b}", CLEAN if ok else LEAK, "split",
                          {f"max_{a}": str(amax), f"min_{b}": str(bmin)}))

    # 2. population: does each row's entity exist at the row's time?
    if db is not None and entity is not None:
        spec = db.schema.entities[entity]
        if not spec.created:
            rep.add(Probe("all", UNCHECKABLE, "population",
                          {"reason": f"entity '{entity}' has no creation time in the schema"}))
        else:
            ent = db.tables[spec.table][[spec.key, spec.created]].drop_duplicates(spec.key)
            ent = ent.rename(columns={spec.key: entity_col, spec.created: "__created"})
            m = task.merge(ent, on=entity_col, how="left")
            created = pd.to_datetime(m["__created"])
            bad = m[created > m[time_col]]
            missing = int(created.isna().sum())
            st = LEAK if len(bad) else CLEAN
            rep.add(Probe("all", st, "population",
                          {"n_violations": int(len(bad)), "n_rows": int(len(m)),
                           "n_without_creation_time": missing}))
            for _, r in bad.head(3).iterrows():
                rep.witnesses.append({"entity": r[entity_col], "row_time": str(r[time_col]),
                                      "created": str(r["__created"])})
            if missing:
                rep.notes.append(f"{missing} rows reference entities without a creation time")

    # 3. label horizon: labels for t must be computable from D|(t+h)
    if label_program is not None:
        if db is None or horizon_days is None:
            raise ValueError("label check needs a schema database and --horizon-days")
        h = pd.Timedelta(days=horizon_days)
        times = np.sort(task[time_col].unique())
        if len(times) > max_times:
            times = times[np.linspace(0, len(times) - 1, max_times).astype(int)]
        for t in times:
            t = pd.Timestamp(t)
            ids = task.loc[task[time_col] == t, entity_col].to_numpy()
            try:
                full = call_isolated(label_program, (db.tables, ids, t), timeout, mem_mb)
                cut = call_isolated(label_program, (db.truncate(t + h).tables, ids, t),
                                    timeout, mem_mb)
            except ProgramError as e:
                rep.add(Probe(_ts(t), ERROR, "horizon", {"error": str(e)}))
                continue
            cols = frame_diff(_as_frame(full, ids), _as_frame(cut, ids), atol)
            rep.add(Probe(_ts(t), LEAK if cols else CLEAN, "horizon", {"columns": cols}))
            if cols and not cols[0].startswith("<"):
                for w in differing_rows(_as_frame(full, ids), _as_frame(cut, ids), cols[0], atol, 1):
                    rep.witnesses.append({"time": _ts(t), "label_reads_beyond": str(t + h), **w})
            # lower boundary: events stamped exactly at t are history, not outcome
            nudged = db.nudge_past(t)
            if nudged is not db and any((rt == t).any() for rt in db.row_time.values()
                                         if rt is not None):
                try:
                    nb = call_isolated(label_program, (nudged.tables, ids, t), timeout, mem_mb)
                except ProgramError as e:
                    rep.add(Probe(_ts(t), ERROR, "boundary", {"error": str(e)}))
                    continue
                bcols = frame_diff(_as_frame(full, ids), _as_frame(nb, ids), atol)
                rep.add(Probe(_ts(t), LEAK if bcols else CLEAN, "boundary", {"columns": bcols}))
                if bcols:
                    rep.witnesses.append({"time": _ts(t), "label_counts_events_at_t": True})
    return rep.finish()


def _as_frame(x, ids):
    if isinstance(x, pd.DataFrame):
        return x
    if isinstance(x, pd.Series):
        return x.to_frame("label")
    return pd.DataFrame({"label": np.asarray(x)}, index=pd.Index(ids))


# ===================================================== model / ICL / agent ==

class Runner:
    """Runs a predictor on (history, query) and returns one score per query row.

    Either a command template (an agent-written script with its own CLI) or a
    Python callable predict(history: DataFrame, query: DataFrame) -> array.
    """

    def __init__(self, cmd=None, program=None, pred_col=None, fmt="parquet",
                 timeout=600, mem_mb=4096, cols=None, query_splits=("val", "test"),
                 hide_query_target=False):
        if (cmd is None) == (program is None):
            raise ValueError("give exactly one of a command template or a program")
        self.cmd, self.program, self.pred_col, self.fmt = cmd, program, pred_col, fmt
        self.timeout, self.mem_mb, self.cols = timeout, mem_mb, cols or {}
        self.query_splits, self.hide = query_splits, hide_query_target

    def __str__(self):
        return self.cmd or str(self.program)

    def __call__(self, history: pd.DataFrame, query: pd.DataFrame) -> np.ndarray:
        q = query.copy()
        if self.hide and self.cols.get("target_col") in q:
            q[self.cols["target_col"]] = np.nan
        if self.program is not None:
            out = call_isolated(self.program, (history.reset_index(drop=True),
                                               q.reset_index(drop=True)),
                                self.timeout, self.mem_mb)
            return self._scores(out, len(q))
        with tempfile.TemporaryDirectory(prefix="strata_") as d:
            d = Path(d)
            self._write(history, d / f"train.{self.fmt}")
            for s in self.query_splits:
                self._write(q, d / f"{s}.{self.fmt}")
            out = d / "pred.csv"
            mapping = dict(task_dir=str(d), out=str(out), split=self.query_splits[-1],
                           train=str(d / f"train.{self.fmt}"),
                           query=str(d / f"{self.query_splits[-1]}.{self.fmt}"), **self.cols)
            run_command(self.cmd, mapping, self.timeout, self.mem_mb)
            if not out.exists():
                raise ProgramError(f"program wrote no prediction file to {out}")
            return self._scores(pd.read_csv(out), len(q))

    def _write(self, df, path):
        if self.fmt == "parquet":
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)

    def _scores(self, out, n):
        if isinstance(out, pd.DataFrame):
            col = self.pred_col
            if col is None:
                skip = {v for v in self.cols.values()}
                num = [c for c in out.columns if c not in skip
                       and pd.api.types.is_numeric_dtype(out[c])]
                if not num:
                    raise ProgramError(f"no numeric prediction column in {list(out.columns)}")
                col = num[-1]
            out = out[col]
        s = np.asarray(out, dtype="float64").reshape(-1)
        if len(s) != n:
            raise ProgramError(f"expected {n} predictions, got {len(s)}")
        return s


def pick_query_times(df, time_col, k=3, min_rows=10, lo=0.5, hi=0.9):
    """k query times inside the history, each with at least min_rows rows."""
    t = pd.to_datetime(df[time_col])
    counts = t.value_counts().sort_index()
    counts = counts[counts >= min_rows]
    if counts.empty:
        return []
    qs = np.quantile(np.arange(len(counts)), np.linspace(lo, hi, k)).round().astype(int)
    return [counts.index[i] for i in sorted(set(qs))]


def _auc(y, s):
    y = np.asarray(y, dtype="float64")
    ok = ~np.isnan(y)
    y, s = y[ok], s[ok]
    if len(np.unique(y)) != 2:
        return None
    pos, neg = s[y == 1], s[y == 0]
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def check_history(layer, runner, data, time_col, entity_col, target_col=None,
                  horizon_days=0, query_times=None, k=3, min_query=10, atol=1e-6,
                  determinism=True):
    """Model and ICL layers. For a query time t the predictor gets
         at t:   rows whose label was known by t  (time + horizon <= t)
         full:   every row except the query rows themselves.
    Different predictions mean the layer let rows from after t in."""
    rep = Report(layer, str(runner), meta={"rows": int(len(data)), "horizon_days": horizon_days})
    data = data.copy()
    data[time_col] = pd.to_datetime(data[time_col])
    times = query_times or pick_query_times(data, time_col, k, min_query)
    if not times:
        rep.add(Probe("-", UNCHECKABLE, "witness", {"reason": "no time with enough query rows"}))
        return rep.finish()
    h = pd.Timedelta(days=horizon_days)
    for i, t in enumerate(times):
        t = pd.Timestamp(t)
        query = data[data[time_col] == t]
        past = data[data[time_col] + h <= t] if h > pd.Timedelta(0) else data[data[time_col] < t]
        full = data[data[time_col] != t]
        n_future = int((full[time_col] > t).sum() + ((full[time_col] <= t) & (full[time_col] + h > t)).sum())
        if len(past) == 0:
            rep.add(Probe(_ts(t), UNCHECKABLE, "witness", {"reason": "empty history at t"}))
            continue
        try:
            s_past = runner(past, query)
            if determinism and i == 0:
                again = runner(past, query)
                if np.nanmax(np.abs(again - s_past)) > atol:
                    rep.add(Probe(_ts(t), UNCHECKABLE, "determinism",
                                  {"max_abs_diff": float(np.nanmax(np.abs(again - s_past)))}))
                    rep.notes.append("program is not deterministic on identical input; "
                                     "differences at other times would not be evidence")
                    break
            s_full = runner(full, query)
        except ProgramError as e:
            rep.add(Probe(_ts(t), ERROR, "run", {"error": str(e)}))
            continue
        d = np.abs(s_full - s_past)
        leak = bool(np.nanmax(d) > atol)
        detail = {"max_abs_diff": float(np.nanmax(d)), "n_query": int(len(query)),
                  "n_history_at_t": int(len(past)), "n_rows_after_t": n_future}
        if target_col and target_col in query:
            detail["auc_at_t"] = _auc(query[target_col], s_past)
            detail["auc_full"] = _auc(query[target_col], s_full)
        rep.add(Probe(_ts(t), LEAK if leak else CLEAN, "witness", detail))
        if leak:
            j = int(np.nanargmax(d))
            rep.witnesses.append({"time": _ts(t), "entity": _plain(query[entity_col].iloc[j]),
                                  "score_at_t": float(s_past[j]), "score_full": float(s_full[j]),
                                  "rows_after_t_added": n_future})
    return rep.finish()


def anonymize(df, entity_col, time_col, id_cols=(), text_cols=None, shift_days=0, variant=0):
    """Order-preserving anonymisation: identities and texts are replaced, but
    every comparison a model can make on them (order, equality) is kept, so a
    model that learns only from the data cannot tell the copies apart.
    `variant` gives a different but equally valid renaming."""
    out = df.copy()
    stride, base, tag = (7, 1000003, "e") if variant == 0 else (13, 5000011, "k")
    for c in [entity_col, *id_cols]:
        vals = np.sort(pd.unique(out[c].dropna()))
        mapping = {v: i * stride + base for i, v in enumerate(vals)} \
            if pd.api.types.is_numeric_dtype(out[c]) else {v: f"{tag}{i:07d}" for i, v in enumerate(vals)}
        out[c] = out[c].map(mapping)
    if text_cols is None:
        text_cols = [c for c in out.columns if c not in (entity_col, time_col, *id_cols)
                     and (pd.api.types.is_object_dtype(out[c]) or pd.api.types.is_string_dtype(out[c]))]
    for c in text_cols:
        vals = np.sort(pd.unique(out[c].dropna().astype(str)))
        out[c] = out[c].astype(str).map({v: f"{tag}v{i:05d}" for i, v in enumerate(vals)}).where(out[c].notna())
    if shift_days:
        out[time_col] = pd.to_datetime(out[time_col]) + pd.Timedelta(days=shift_days)
    return out


def check_agent(runner, train, query, entity_col, time_col, target_col=None, id_cols=(),
                shift_days=0, atol=1e-6, determinism=True):
    """Does the program's output depend on who the entities are, beyond what the
    data says about them? The program runs on the original data and on two
    different order-preserving anonymisations.

      both anonymisations agree, original differs  -> LEAK (the real identities
          carry information the data does not: recall or an external lookup)
      the anonymisations disagree with each other    -> UNCHECKABLE (the output
          depends on how identities are spelled, e.g. hashed ID features)
      all three agree                                -> CLEAN
    """
    rep = Report("agent", str(runner), meta={"shift_days": shift_days, "id_cols": list(id_cols)})
    both = pd.concat([train.assign(__q=0), query.assign(__q=1)], ignore_index=True)

    def anon(variant):
        a = anonymize(both, entity_col, time_col, id_cols, shift_days=shift_days, variant=variant)
        a_train = a[a.__q == 0].drop(columns="__q")
        a_query = a[a.__q == 1].drop(columns="__q")
        if target_col:
            a_train[target_col] = train[target_col].to_numpy()
            a_query[target_col] = query[target_col].to_numpy()
        return a_train, a_query

    try:
        s = runner(train, query)
        if determinism and np.nanmax(np.abs(runner(train, query) - s)) > atol:
            rep.add(Probe("-", UNCHECKABLE, "determinism", {}))
            rep.notes.append("program is not deterministic on identical input")
            return rep.finish()
        s1 = runner(*anon(0))
        s2 = runner(*anon(1))
    except ProgramError as e:
        rep.add(Probe("-", ERROR, "run", {"error": str(e)}))
        return rep.finish()
    d_orig = np.abs(s - s1)
    d_anon = np.abs(s1 - s2)
    detail = {"max_abs_diff": float(np.nanmax(d_orig)),
              "max_abs_diff_between_anonymizations": float(np.nanmax(d_anon)),
              "n_query": int(len(query))}
    if target_col:
        detail["auc_original"] = _auc(query[target_col], s)
        detail["auc_anonymized"] = _auc(query[target_col], s1)
    if np.nanmax(d_anon) > atol:
        rep.add(Probe("-", UNCHECKABLE, "identity", detail))
        rep.notes.append("output depends on how identities are spelled (e.g. hashed or "
                         "numeric ID features); identity recall cannot be separated from that")
    elif np.nanmax(d_orig) > atol:
        rep.add(Probe("-", LEAK, "identity", detail))
        j = int(np.nanargmax(d_orig))
        rep.witnesses.append({"entity": _plain(query[entity_col].iloc[j]),
                              "score_original": float(s[j]), "score_anonymized": float(s1[j])})
        rep.notes.append("output depends on the real identities: recall from pretraining "
                         "or an external lookup")
    else:
        rep.add(Probe("-", CLEAN, "identity", detail))
    return rep.finish()


def _plain(v):
    return v.item() if isinstance(v, np.generic) else v
