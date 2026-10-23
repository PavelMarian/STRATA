"""LLM-assisted availability schema: an optional helper for `strata init`.

    strata init --data DIR --out schema.json --llm [--docs README.md] [--no-samples]

What the model does: it reads a profile of the files (column names, types,
date ranges, a few sample values unless --no-samples) and the heuristic draft,
optionally the data's documentation, and proposes, for every table, its row
time, late-filled and planned dates, snapshot columns, mutable columns and
the entities. The meaning of a column is exactly what heuristics cannot see.

What it never does: produce a verdict, or code. Its answer is JSON in a fixed
schema; every decision is checked against the data (strata.evidence), the
contradictions go back to the model for at most `rounds` revisions, and the
result is written as a draft whose decisions, reasons and remaining findings
are listed under "_review" for a person to confirm. Checks never depend on a
model: the schema they run on is a reviewed file.

The model is reached through OpenRouter (chat completions with a JSON-schema
response format; key in OPENROUTER_API_KEY). The profile, and sample values
unless --no-samples, leave the machine. Run it where the network step is
allowed; the process that executes code under test never holds the key.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .evidence import check_schema
from .infer import infer_schema
from .profile import profile

MODEL = "anthropic/claude-opus-5.5"
URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM = """You prepare availability schemas for STRATA, a tool that checks whether \
ML pipelines over time-stamped relational data use information that did not exist \
at prediction time t. STRATA rebuilds the database as it was at t from your schema, \
so every decision changes which data a pipeline is allowed to see.

For every table decide:
- kind "timed": a row exists from its row-time column on. The row time is when the \
row was created, never a later or planned date.
- kind "inherits": the table has no creation time of its own (order lines, payments) \
and a row exists when its parent row does; give the parent table and the key.
- kind "static": a reference table whose rows do not live in time.
- self_available: date columns filled in after the row was created, known only at \
their own value (delivery date, return date, answer time).
- planned: date columns written together with the row that lie in its future \
(estimated delivery, due date, shipping limit). They are known at the row time.
- snapshots: columns stored as their end-of-data state instead of their history \
(final status, current price, career totals, current balance). valid_from is \
"end_of_data" if the value is only valid at the end, "column" with a date column \
of the same table from which it is valid, or "date" with an ISO date.
- unknown: mutable columns whose validity cannot be determined. Prefer unknown over \
a guess: STRATA then reports programs that read them as unverifiable instead of clean.
Entities: the things predictions are made for, with their key and, if a column \
records it, their creation time.

Use only tables and columns that appear in the profile. Give a short reason for every \
table and entity, citing the evidence (names, date ranges, documentation). List in \
"questions" what a person must confirm because neither the names nor the data settle it."""

_STR_LIST = {"type": "array", "items": {"type": "string"}}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tables": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": ["timed", "inherits", "static"]},
                "time": {"type": "string", "description": "row-time column; empty unless timed"},
                "inherits_from": {"type": "string", "description": "parent table; empty unless inherits"},
                "inherits_key": {"type": "string", "description": "key shared with the parent"},
                "self_available": _STR_LIST,
                "planned": _STR_LIST,
                "snapshots": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string"},
                        "valid_from": {"type": "string", "enum": ["end_of_data", "column", "date"]},
                        "value": {"type": "string", "description": "column name or ISO date; empty for end_of_data"},
                    },
                    "required": ["column", "valid_from", "value"],
                    "additionalProperties": False}},
                "unknown": _STR_LIST,
                "reason": {"type": "string"},
            },
            "required": ["name", "kind", "time", "inherits_from", "inherits_key", "self_available",
                         "planned", "snapshots", "unknown", "reason"],
            "additionalProperties": False}},
        "entities": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "table": {"type": "string"},
                "key": {"type": "string"},
                "created": {"type": "string", "description": "creation-time column; empty if none"},
                "reason": {"type": "string"},
            },
            "required": ["name", "table", "key", "created", "reason"],
            "additionalProperties": False}},
        "questions": _STR_LIST,
    },
    "required": ["tables", "entities", "questions"],
    "additionalProperties": False,
}


class SchemaAgentError(RuntimeError):
    pass


def to_schema(proposal: dict, files: dict, data_dir, dates: dict | None = None) -> dict:
    """The model's answer -> a STRATA schema dict (files: table -> file name;
    dates: table -> columns that parse as dates, loaded as dates whatever their role)."""
    tables = {}
    for t in proposal["tables"]:
        name = t["name"]
        if name not in files:
            continue                            # an invented table never enters the schema
        spec = {"path": files[name]}
        if t["kind"] == "timed" and t["time"]:
            spec["time"] = t["time"]
        elif t["kind"] == "inherits" and t["inherits_from"] and t["inherits_key"]:
            spec["time_from"] = {"table": t["inherits_from"], "key": t["inherits_key"]}
        else:
            spec["static"] = True
        for k in ("self_available", "planned", "unknown"):
            if t[k]:
                spec[k] = list(t[k])
        vt = {}
        for snap in t["snapshots"]:
            vt[snap["column"]] = None if snap["valid_from"] == "end_of_data" else snap["value"]
        if vt:
            spec["value_time"] = vt
        parse = [snap["value"] for snap in t["snapshots"] if snap["valid_from"] == "column"]
        parse += (dates or {}).get(name, [])
        if parse:
            spec["parse_dates"] = sorted(set(parse))
        tables[name] = spec
    for name, f in files.items():                # tables the model skipped stay, as static
        tables.setdefault(name, {"path": f, "static": True})
    entities = {e["name"]: {"table": e["table"], "key": e["key"], "created": e["created"] or None}
                for e in proposal["entities"] if e["table"] in files}
    return {"name": Path(data_dir).name, "root": str(Path(data_dir).resolve()),
            "tables": tables, "entities": entities}


def _post(payload, api_key, timeout=900):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {api_key}",
                                          "Content-Type": "application/json",
                                          "X-Title": "STRATA schema agent"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SchemaAgentError(f"OpenRouter HTTP {e.code}: {e.read()[:500]!r}") from e
    except urllib.error.URLError as e:
        raise SchemaAgentError(f"cannot reach OpenRouter: {e.reason}") from e


def _ask(messages, model, api_key, post):
    """One structured answer: (assistant text, parsed proposal)."""
    payload = {"model": model, "max_tokens": 16000,
               "messages": [{"role": "system", "content": SYSTEM}] + messages,
               "response_format": {"type": "json_schema",
                                   "json_schema": {"name": "strata_schema", "strict": True,
                                                   "schema": OUTPUT_SCHEMA}},
               "provider": {"require_parameters": True}}
    r = post(payload, api_key)
    if "error" in r:
        raise SchemaAgentError(f"OpenRouter error: {str(r['error'])[:500]}")
    choice = r["choices"][0]
    if choice.get("finish_reason") in ("length", "max_tokens"):
        raise SchemaAgentError("answer truncated at max_tokens; too many tables for one request")
    text = choice["message"].get("content") or ""
    try:
        return text, json.loads(text)
    except json.JSONDecodeError:
        raise SchemaAgentError(f"the model returned no JSON (finish_reason "
                               f"{choice.get('finish_reason')}): {text[:300]!r}")


def llm_schema(data_dir, docs=None, samples=True, model=MODEL, rounds=2, log=print,
               api_key=None, post=_post):
    """Draft a schema with the model, revise it against the data, return a
    schema dict with "_review" (decisions, reasons, open findings, questions)."""
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SchemaAgentError("OPENROUTER_API_KEY is not set")
    data_dir = Path(data_dir)
    prof = profile(data_dir, samples=samples)
    heuristic = infer_schema(data_dir)
    files = {t: p["file"] for t, p in prof.items()}
    dates = {t: [c for c, i in p["columns"].items() if i["dtype"] == "date"] for t, p in prof.items()}
    heur = {k: v for k, v in heuristic.items() if k not in ("root",)}
    content = ("Profile of the data files (sampled rows):\n" + json.dumps(prof, indent=1, default=str)
               + "\n\nDraft from STRATA's name/date heuristics, with its decisions under _review "
               "(a starting point; correct it where it is wrong):\n" + json.dumps(heur, indent=1))
    if docs:
        content += "\n\nDocumentation of the data:\n" + Path(docs).read_text(encoding="utf-8")
    messages = [{"role": "user", "content": content}]
    findings, proposal = [], None
    for rnd in range(rounds + 1):
        text, proposal = _ask(messages, model, api_key, post)
        schema = to_schema(proposal, files, data_dir, dates)
        findings = check_schema(schema, data_dir)
        errors = [f for f in findings if f["level"] == "error"]
        log(f"round {rnd}: {len(errors)} errors, {len(findings) - len(errors)} warnings")
        if not findings or rnd == rounds:
            break
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content":
                      "STRATA checked this schema against the data. Findings:\n"
                      + json.dumps(findings, indent=1)
                      + "\nFix every error. For each warning, change the decision or keep it and "
                        "say why in the table's reason. Return the complete schema again."}]
    schema["_review"] = (
        [f"{t['name']}: {t['kind']}"
         + (f" (time {t['time']})" if t["kind"] == "timed" else "")
         + (f" (from {t['inherits_from']} via {t['inherits_key']})" if t["kind"] == "inherits" else "")
         + f" -- {t['reason']}" for t in proposal["tables"]]
        + [f"entity {e['name']} = {e['table']}.{e['key']}, created {e['created'] or 'unknown'}"
           f" -- {e['reason']}" for e in proposal["entities"]]
        + [f"{f['level'].upper()} {f['table']}.{f['column']}: {f['message']}" for f in findings]
        + [f"QUESTION: {q}" for q in proposal["questions"]])
    schema["_provenance"] = {"drafted_by": model, "via": "openrouter", "revision_rounds": rnd,
                             "samples_sent": samples, "docs": str(docs) if docs else None}
    return schema
