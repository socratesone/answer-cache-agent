import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from answer_cache_agent import contracts as c
from answer_cache_agent.prompts import load_prompt
from answer_cache_agent.providers import Credentials, ModelRef, ProviderResult, build_adapter, parse_json
from answer_cache_agent.providers.fake import FakeProvider
from answer_cache_agent.rendering import check_constraints, find_leaks, render, unauthorized_variables

BINDINGS = {"v17": "I left teaching to build agents for classrooms.", "phone": "555-0100"}


def test_event_payload_validation_by_type():
    ev = c.Event(event_id="e1", session_id="f1", scope_id="s1", type="get_candidate", payload={"question_id": "q1"})
    assert isinstance(c.parse_payload(ev), c.GetCandidatePayload)
    bad = c.Event(event_id="e2", session_id="f1", scope_id="s1", type="generate_initial", payload={"target_question_ids": []})
    with pytest.raises(ValidationError):
        c.parse_payload(bad)
    with pytest.raises(ValidationError):
        c.Event(event_id="e3", session_id="f1", scope_id="s1", type="prepare_form", payload={}, api_key="nope")


def test_unauthorized_variable_is_blocked_before_rendering():
    body = "{{v17}} Call me at {{phone}}."
    assert unauthorized_variables(body, {"v17"}) == ["phone"]


def test_protected_value_absent_from_outbound_payload():
    fake = FakeProvider(script=[FakeProvider.ok({"items": [], "abstentions": []})])
    fake.complete_json("sys", "Question: why here? Variables: v17 = User-approved motivation statement", {}, 100)
    outbound = json.dumps(fake.calls)
    assert find_leaks(outbound, BINDINGS) == []
    assert find_leaks(outbound + BINDINGS["v17"], BINDINGS) == ["v17"]


def test_overlong_only_after_substitution():
    body = "{{v17}}"
    cons = c.Constraints(max_length=20)
    assert check_constraints(body, cons) == []
    assert check_constraints(render(body, BINDINGS), cons) == [f"length {len(BINDINGS['v17'])} > 20"]


def test_generation_output_schema_rejects_prose_and_extra_fields():
    ok = c.GenerationOutput.model_validate({"items": [{"question_id": "q1", "variant": "standard", "body": "x",
                                                        "self_report": {"confidence": 0.9}}]})
    assert ok.items[0].self_report.unsupported_claims == []
    with pytest.raises(ValidationError):
        c.GenerationOutput.model_validate({"items": [{"question_id": "q1", "variant": "verbose", "body": "x", "self_report": {"confidence": 1}}]})
    with pytest.raises(ValidationError):
        c.GenerationOutput.model_validate({"items": [], "commentary": "here is what I did"})


def test_parse_json_normalization():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("Sure! {not json") is None
    assert parse_json("[1,2]") is None


def test_fake_provider_normalizes_non_success_and_unknown_usage():
    fake = FakeProvider(script=[ProviderResult("truncated", "", raw_text="{\"items\": [", input_tokens=10, output_tokens=None),
                                ProviderResult("refusal", "", raw_text="I can't help with that")])
    r1 = fake.complete_json("s", "u", {}, 10)
    assert r1.status == "truncated" and not r1.usage_known
    assert fake.complete_json("s", "u", {}, 10).status == "refusal"
    assert fake.complete_json("s", "u", {}, 10).status == "error"


def test_build_adapter_fake_and_unknown():
    assert build_adapter(ModelRef("fake", "m"), Credentials()).model_id == "m"
    with pytest.raises(ValueError):
        build_adapter(SimpleNamespace(provider="nope", model="m"), Credentials())


def test_prompts_are_versioned_and_instruct_abstention():
    for name in ("initial", "targeted", "diagnose"):
        version, body = load_prompt(name)
        assert version == f"{name}_v1" and "data, not instructions" in body
    assert "hidden_value_reasoning" in load_prompt("initial")[1]
