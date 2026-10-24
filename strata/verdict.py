"""Verdict vocabulary shared by all layers.

LEAK         an observed difference between the run on the full database and the
             run on its state at t; always carries at least one witness.
CLEAN        no difference at the tested times. Nothing more is claimed.
UNCHECKABLE  the check could not be decided: missing availability information,
             a nondeterministic program, or a read of a column whose
             availability is unknown. Never counted as clean.
ERROR        the program crashed, timed out or broke its output contract.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

LEAK, CLEAN, UNCHECKABLE, ERROR = "LEAK", "CLEAN", "UNCHECKABLE", "ERROR"
EXIT_CODES = {CLEAN: 0, LEAK: 1, UNCHECKABLE: 2, ERROR: 3}
_PRIORITY = [LEAK, ERROR, UNCHECKABLE, CLEAN]


@dataclass
class Probe:
    """One comparison at one time t."""
    time: str
    status: str
    kind: str = "witness"             # witness | canary | unknown | horizon | population | ...
    detail: dict = field(default_factory=dict)


@dataclass
class Report:
    layer: str
    target: str
    status: str = CLEAN
    probes: list = field(default_factory=list)
    witnesses: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic, repr=False)

    def add(self, probe: Probe):
        self.probes.append(probe)

    def finish(self):
        statuses = {p.status for p in self.probes} or {UNCHECKABLE}
        self.status = next(s for s in _PRIORITY if s in statuses)
        self.meta["wall_seconds"] = round(time.monotonic() - self.started, 2)
        return self

    @property
    def exit_code(self):
        return EXIT_CODES[self.status]

    def to_dict(self):
        d = asdict(self)
        d.pop("started", None)
        return d

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, default=str, ensure_ascii=False)

    def summary(self):
        lines = [f"[{self.layer}] {self.target}: {self.status}"]
        for p in self.probes:
            extra = ""
            d = p.detail
            if d.get("columns"):
                extra = " columns=" + ",".join(map(str, d["columns"][:6]))
            elif "max_abs_diff" in d:
                extra = f" max|Δ|={d['max_abs_diff']:.4g}"
                if d.get("auc_at_t") is not None and d.get("auc_full") is not None:
                    extra += f"  AUC at t={d['auc_at_t']:.3f} full={d['auc_full']:.3f}"
            elif d.get("error"):
                extra = " " + d["error"][:120]
            elif "n_violations" in d:
                extra = f" violations={d['n_violations']}"
            lines.append(f"  t={p.time} {p.kind:<10} {p.status}{extra}")
        for w in self.witnesses[:5]:
            lines.append("  witness: " + json.dumps(w, default=str, ensure_ascii=False))
        for n in self.notes:
            lines.append("  note: " + n)
        return "\n".join(lines)
