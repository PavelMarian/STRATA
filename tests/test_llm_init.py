"""The LLM schema agent, with a scripted OpenRouter endpoint in place of the network."""
import json

import pytest

from conftest import make_tables
from strata import Schema, TemporalDB
from strata.llm_init import SchemaAgentError, llm_schema, to_schema


def table(name, kind, time="", parent="", key="", self_av=(), planned=(), snaps=(), unknown=()):
    return {"name": name, "kind": kind, "time": time, "inherits_from": parent, "inherits_key": key,
            "self_available": list(self_av), "planned": list(planned), "snapshots": list(snaps),
            "unknown": list(unknown), "reason": f"{name} reason"}


GOOD = {
    "tables": [
        table("customers", "timed", time="signup"),
        table("orders", "timed", time="ts", self_av=["delivered_at", "rated_at"], unknown=["status"],
              snaps=[{"column": "rating", "valid_from": "column", "value": "rated_at"}]),
        table("items", "inherits", parent="orders", key="order_id"),
    ],
    "entities": [{"name": "customer", "table": "customers", "key": "customer_id",
                  "created": "signup", "reason": "signup is the creation time"}],
    "questions": ["Is status overwritten when an order is returned?"],
}
BAD = json.loads(json.dumps(GOOD))
BAD["tables"][1]["time"] = "order_time"                     # no such column
BAD["tables"].append(table("ghost", "static"))             # invented table


class Scripted:
    """Stands in for the HTTP call: returns the scripted answers in order."""

    def __init__(self, answers, finish="stop", raw=None):
        self.answers, self.calls, self.finish, self.raw = list(answers), [], finish, raw

    def __call__(self, payload, api_key):
        self.calls.append(payload)
        if self.raw is not None:
            return self.raw
        return {"choices": [{"finish_reason": self.finish,
                             "message": {"role": "assistant", "content": json.dumps(self.answers.pop(0))}}]}


def run(shop_dir, post, **kw):
    return llm_schema(shop_dir, post=post, api_key="test", log=lambda *_: None, **kw)


@pytest.fixture()
def shop_dir(tmp_path):
    for name, df in make_tables().items():
        df.to_csv(tmp_path / f"{name}.csv", index=False)
    return tmp_path


def test_revises_against_data_and_lists_decisions(shop_dir):
    post = Scripted([BAD, GOOD])
    schema = run(shop_dir, post)
    assert len(post.calls) == 2
    second = post.calls[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert "order_time" in second[3]["content"]
    assert schema["tables"]["orders"]["time"] == "ts"
    assert "ghost" not in schema["tables"]
    assert schema["tables"]["orders"]["value_time"] == {"rating": "rated_at"}
    assert any(r.startswith("QUESTION") for r in schema["_review"])
    assert schema["_provenance"]["revision_rounds"] == 1
    db = TemporalDB.load(Schema.from_dict(schema))             # the result is a usable schema
    assert db.row_time["items"] is not None


def test_request_shape(shop_dir):
    post = Scripted([GOOD])
    run(shop_dir, post)
    p = post.calls[0]
    assert p["model"] == "anthropic/claude-opus-5.5"
    assert p["response_format"]["type"] == "json_schema"
    assert p["response_format"]["json_schema"]["strict"] is True
    assert p["provider"]["require_parameters"] is True


def test_no_samples_sends_no_values(shop_dir):
    post = Scripted([GOOD])
    run(shop_dir, post, samples=False)
    assert "returned" not in post.calls[0]["messages"][1]["content"]


def test_truncation_and_provider_errors(shop_dir):
    with pytest.raises(SchemaAgentError, match="truncated"):
        run(shop_dir, Scripted([GOOD], finish="length"))
    with pytest.raises(SchemaAgentError, match="OpenRouter error"):
        run(shop_dir, Scripted([], raw={"error": {"message": "no provider supports json_schema"}}))


def test_missing_key(shop_dir, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SchemaAgentError, match="OPENROUTER_API_KEY"):
        llm_schema(shop_dir, log=lambda *_: None)


def test_to_schema_keeps_skipped_tables_static(shop_dir):
    s = to_schema({"tables": [], "entities": [], "questions": []},
                  {"customers": "customers.csv"}, shop_dir)
    assert s["tables"]["customers"]["static"] is True
