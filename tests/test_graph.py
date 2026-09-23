"""End-to-end event flows through the four-node graph with scripted providers (PRD §13 scenarios)."""
import json
import uuid

import pytest

from answer_cache_agent.embeddings import HashEmbedder
from answer_cache_agent.graph import Agent, RuntimeDeps
from answer_cache_agent.providers.base import ProviderResult
from answer_cache_agent.providers.fake import FakeProvider
from answer_cache_agent.rendering import find_leaks

APPROVED = dict(disclosure="model_visible", approved_by="user", approved_at="2026-09-01")
BINDINGS = {"v17": "I left classroom teaching to build agents for schools.", "phone": "555-0100"}


def generator(system: str, user: str) -> ProviderResult:
    """Scripted 'model': cites the first template/evidence in its bundle, uses only permitted variables."""
    u = json.loads(user)
    b = u["CONTEXT BUNDLE"]
    qid = b["question"]["id"]
    refs = dict(template_refs=[b["templates"][0]["id"]] if b["templates"] else [],
                evidence_refs=[b["evidence"][0]["id"]] if b["evidence"] else [])
    var = "{{v17}} " if any(v["id"] == "v17" for v in u["PERMITTED VARIABLES"]) else ""
    rep = {"confidence": 0.9}
    if "TARGET QUESTIONS" in u:
        items = [dict(question_id=qid, variant="standard", body=f"{var}Standard answer for {qid}.", variables=["v17"] if var else [], self_report=rep, **refs),
                 dict(question_id=qid, variant="concise", body=f"{var}Short {qid}.", variables=["v17"] if var else [], self_report=rep, **refs)]
    else:
        notes = ";".join(",".join(r["reasons"]) for r in u["REJECTED"]) or "none"
        diag = (u.get("DIAGNOSIS") or {}).get("diagnosis", "")
        items = [dict(question_id=qid, variant="alternative", body=f"Alt {i} for {qid} [reasons:{notes}] [diag:{diag}]",
                      variables=[], self_report=rep, **refs) for i in range(7)]  # over the cap on purpose
    return FakeProvider.ok({"items": items, "abstentions": []})


def diagnoser(system: str, user: str) -> ProviderResult:
    u = json.loads(user)
    return FakeProvider.ok({"question_id": u["question"]["id"], "diagnosis": "wrong emphasis", "strategy_changes": ["lead with platform work"]})


@pytest.fixture
def env(tmp_path):
    routine, advanced = FakeProvider("fake-1"), FakeProvider("fake-adv")
    routine.script.extend([generator] * 50)
    advanced.script.extend([diagnoser] * 10)
    agent = Agent(RuntimeDeps(db_path=str(tmp_path / "a.db"), bindings=BINDINGS, embedder=HashEmbedder(),
                              adapters={"routine": routine, "advanced": advanced}))
    r = agent._repo("s1")
    r.add_dimension("role_family", "Role family"); r.add_value("agent_engineering", "role_family", "AE"); r.add_value("full_stack", "role_family", "FS")
    r.add_dimension("sector", "Sector"); r.add_value("education", "sector", "Edu")
    r.add_variable("v17", "User-approved motivation statement", "text", "verbatim")
    r.add_evidence("E3", "https://example.org/blog", "2026-08", "We ship evaluation tooling with agents.", **APPROVED)
    r.add_intent_alias("motivation", "Why do you want to work here?")
    for tid, ctx in (("A", "full_stack"), ("B", "agent_engineering"), ("C", "education")):
        r.add_template(tid, "motivation", f"{{{{v17}}}} Template {tid} about why work here.", ["v17"], ["E3"], **APPROVED)
        r.assign("template", tid, ctx)
    r.add_intent_alias("relocate", "Are you willing to relocate?")
    r.add_template("R", "relocate", "Yes, willing to relocate for the role.", [], ["E3"], **APPROVED)
    return agent, routine, advanced


def ev(type, payload, session="f1", expected=None, scope="s1", event_id=None):
    return {"event_id": event_id or str(uuid.uuid4()), "session_id": session, "scope_id": scope, "type": type,
            "expected_revision": expected, "payload": payload}


FORM = {"questions": [{"id": "q1", "text": "Why do you want to work here?", "constraints": {"max_length": 400}},
                      {"id": "q2", "text": "Are you willing to relocate?"},
                      {"id": "q3", "text": "Full name", "prefilled": True}],
        "page_url": "https://jobs.example.edu/apply", "hints": [{"dimension": "role_family", "value": "agent_engineering", "source": "user"}],
        "rules": [{"id": "edu", "match_field": "page_url", "pattern": r"\.edu/", "dimension": "sector", "value": "education"}]}


def prepared(agent):
    r = agent.handle_event(ev("prepare_form", FORM))
    assert r["status"] == "ready"
    return r["revision"]


def test_prepare_makes_no_paid_call_and_applies_rules(env):
    agent, routine, _ = env
    rev = prepared(agent)
    assert routine.calls == [] and rev.startswith("rev-")
    assert agent._repo("s1").session("f1")["state"]["values"] == {"role_family": ["agent_engineering"], "sector": ["education"]}


def test_initial_generation_two_variants_only_requested_returned(env):
    agent, routine, _ = env
    rev = prepared(agent)
    r = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"], "authorized_question_ids": ["q2", "q3"]}, expected=rev))
    assert r["status"] == "ready", r
    assert [x["variant"] for x in r["candidates"]] == ["standard", "concise"] and {x["question_id"] for x in r["candidates"]} == {"q1"}
    assert len(r["cached"]["q2"]) == 2 and "q3" not in r["cached"]
    assert r["usage"]["calls"] == 2 and len(routine.calls) == 2
    assert r["candidates"][0]["ranking"]["policy_version"] == "1"
    top = json.loads(routine.calls[0]["user"])["CONTEXT BUNDLE"]["templates"][0]["id"]
    assert top in ("B", "C")  # context {agent_engineering, education} outranks A


def test_protected_value_never_leaves(env):
    agent, routine, advanced = env
    rev = prepared(agent)
    agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1", "q2"]}, expected=rev))
    for call in routine.calls + advanced.calls:
        assert find_leaks(call["system"] + call["user"], BINDINGS) == []
    rows = agent.conn.execute("SELECT state_json FROM form_session").fetchall() + agent.conn.execute("SELECT checkpoint FROM checkpoints").fetchall()
    for (blob,) in rows:
        assert BINDINGS["v17"].encode() not in (blob if isinstance(blob, bytes) else blob.encode())


def test_leak_check_catches_json_escaped_values(env):
    """Outbound payloads are json.dumps-encoded; a non-ASCII value must not slip past the gate as \\uXXXX."""
    agent, routine, _ = env
    agent.rt.bindings = {**BINDINGS, "v17": "José Álvarez-Ruiz \"quoted\"\nline"}
    r = agent._repo("s1")
    r.add_template("L", "motivation", "José Álvarez-Ruiz \"quoted\"\nline is in this body {{v17}}", ["v17"], ["E3"], **APPROVED)
    r.assign("template", "L", "agent_engineering")
    rev = prepared(agent)
    n = len(routine.calls)
    res = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev))
    assert len(routine.calls) == n and res["status"] in ("failed", "partial")
    assert any("leak" in d for d in res["diagnostics"]), res["diagnostics"]


def test_scopes_do_not_share_events_or_sessions(env):
    """Event and session ids are client-chosen: the same ids in another scope must be a different event/session."""
    agent, routine, _ = env
    rev = prepared(agent)
    e = ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev)
    first = agent.handle_event(e)
    assert first["candidates"]
    other = agent.handle_event({**e, "scope_id": "s2"})
    assert other["status"] == "failed" and other["candidates"] == [] and "unknown session" in other["diagnostics"][0]
    agent.handle_event(ev("prepare_form", FORM, scope="s2"))  # same session id "f1" in scope s2
    assert agent._repo("s1").session("f1")["revision"] == rev  # s1's session untouched
    assert agent.handle_event(e) == first  # s1 replay still intact


def test_cached_concise_without_model_call_and_replay(env):
    agent, routine, _ = env
    rev = prepared(agent)
    e = ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev)
    first = agent.handle_event(e)
    n = len(routine.calls)
    r = agent.handle_event(ev("get_candidate", {"question_id": "q1", "variant": "concise"}, expected=rev))
    assert r["status"] == "ready" and [x["variant"] for x in r["candidates"]] == ["concise"] and len(routine.calls) == n
    assert agent.handle_event(e) == first and len(routine.calls) == n  # duplicate event replays, no new call
    miss = agent.handle_event(ev("get_candidate", {"question_id": "q2"}, expected=rev))
    assert miss["status"] == "partial" and miss["candidates"] == [] and len(routine.calls) == n


def test_targeted_regeneration_capped_feedback_influences_then_diagnosis_then_needs_feedback(env):
    agent, routine, advanced = env
    rev = prepared(agent)
    init = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev))
    cid = init["candidates"][0]["id"]
    r1 = agent.handle_event(ev("regenerate_question", {"question_id": "q1", "rejected": [{"candidate_id": cid, "reasons": ["too_generic"]}]}, expected=rev))
    assert r1["status"] == "ready" and len(r1["candidates"]) == 5 and all("too_generic" in x["body"] for x in r1["candidates"])
    assert advanced.calls == []  # no evaluator on the first targeted round
    # reject the whole targeted set with reasons -> diagnosis + second round
    for x in r1["candidates"]:
        agent.handle_event(ev("record_feedback", {"outcome": "rejected", "candidate_id": x["id"], "reasons": ["wrong_emphasis"]}, expected=rev))
    r2 = agent.handle_event(ev("regenerate_question", {"question_id": "q1"}, expected=rev))
    assert r2["status"] == "ready" and len(advanced.calls) == 1 and all("diag:wrong emphasis" in x["body"] for x in r2["candidates"])
    for x in r2["candidates"]:
        agent.handle_event(ev("record_feedback", {"outcome": "rejected", "candidate_id": x["id"], "reasons": ["too_long"]}, expected=rev))
    n = len(routine.calls)
    r3 = agent.handle_event(ev("regenerate_question", {"question_id": "q1"}, expected=rev))
    assert r3["status"] == "needs_feedback" and r3["candidates"] == [] and len(routine.calls) == n


def test_exhausted_without_reasons_asks_for_feedback_without_paying(env):
    agent, routine, advanced = env
    rev = prepared(agent)
    agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev))
    r1 = agent.handle_event(ev("regenerate_question", {"question_id": "q1"}, expected=rev))
    for x in r1["candidates"]:
        agent.handle_event(ev("record_feedback", {"outcome": "rejected", "candidate_id": x["id"]}, expected=rev))
    n = len(routine.calls)
    r = agent.handle_event(ev("regenerate_question", {"question_id": "q1"}, expected=rev))
    assert r["status"] == "needs_feedback" and len(routine.calls) == n and advanced.calls == []


def test_hidden_candidate_and_duplicate_feedback(env):
    agent, _, _ = env
    rev = prepared(agent)
    r = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev))
    a, b = r["candidates"]
    agent.handle_event(ev("record_feedback", {"outcome": "shown", "shown": [a["id"]], "alternatives": [b["id"]]}, expected=rev))
    fb = ev("record_feedback", {"outcome": "selected", "candidate_id": a["id"]}, expected=rev)
    agent.handle_event(fb); agent.handle_event(fb)
    repo = agent._repo("s1")
    assert repo.stats(a["template_refs"][0], "*").sel == 1
    assert repo.stats(b["id"], "*") is None and repo.stats(b["template_refs"][0], "*") is None or repo.stats(b["template_refs"][0], "*").rej == 0


def test_missing_evidence_and_generator_abstention(env, tmp_path):
    agent, routine, _ = env
    rev = prepared(agent)
    routine.script.clear()
    routine.script.append(FakeProvider.ok({"items": [], "abstentions": [{"question_id": "q1", "reason": "hidden_value_reasoning",
                                                                          "needed": "years of experience as a disclosed fact"}]}))
    r = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev))
    assert r["status"] == "needs_information" and r["unresolved"][0]["reason"] == "hidden_value_reasoning"
    empty = Agent(RuntimeDeps(db_path=str(tmp_path / "e.db"), embedder=HashEmbedder(), adapters={"routine": routine, "advanced": routine}))
    empty.handle_event(ev("prepare_form", FORM, scope="empty"))
    rev2 = empty._repo("empty").session("f1")["revision"]
    n = len(routine.calls)
    r = empty.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev2, scope="empty"))
    assert r["status"] == "needs_information" and r["unresolved"][0]["reason"] == "insufficient_evidence" and len(routine.calls) == n


def test_unauthorized_variable_and_overlong_are_invalid(env):
    agent, routine, _ = env
    rev = prepared(agent)
    routine.script.clear()
    routine.script.append(FakeProvider.ok({"items": [
        {"question_id": "q1", "variant": "standard", "body": "Call {{phone}} now.", "variables": ["phone"], "template_refs": ["B"], "self_report": {"confidence": 1}},
        {"question_id": "q1", "variant": "concise", "body": "{{v17}} " * 12, "variables": ["v17"], "template_refs": ["B"], "self_report": {"confidence": 1}}]}))
    r = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev))
    assert r["status"] == "failed" and r["candidates"] == []
    probs = [x["validation"]["problems"] for x in agent._repo("s1").candidates("f1", "q1", statuses=("invalid",))]
    assert any("unauthorized variables ['phone']" in p[0] for p in probs) and any("length" in p[0] for p in probs)


def test_stale_form_is_not_reused(env):
    agent, _, _ = env
    rev = prepared(agent)
    agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"]}, expected=rev))
    changed = {**FORM, "questions": FORM["questions"] + [{"id": "q4", "text": "Anything else?"}]}
    r = agent.handle_event(ev("update_form", changed, expected=rev))
    assert r["status"] == "ready" and r["revision"] != rev
    assert agent.handle_event(ev("get_candidate", {"question_id": "q1"}, expected=rev))["status"] == "stale_context"
    fresh = agent.handle_event(ev("get_candidate", {"question_id": "q1"}, expected=r["revision"]))
    assert fresh["status"] == "partial" and fresh["candidates"] == []


def test_budget_exhaustion_stops_with_explicit_status(env):
    agent, routine, _ = env
    rev = prepared(agent)
    r = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1"], "limits": {"max_tokens": 10}}, expected=rev))
    assert r["status"] == "budget_exhausted" and routine.calls == [] and r["usage"]["calls"] == 0


def test_partial_failure_keeps_completed_work_and_uncertain_is_not_retried(env):
    agent, routine, _ = env
    rev = prepared(agent)
    routine.script.clear()
    routine.script.extend([generator, ProviderResult("error", "fake-1", error="ConnectionReset")])
    r = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1", "q2"]}, expected=rev))
    assert r["status"] == "partial" and {x["question_id"] for x in r["candidates"]} == {"q1"}
    assert r["usage"]["uncertain"] == 1 and r["unresolved"][0] == {"question_id": "q2", "reason": "provider_failed", "needed": "ConnectionReset"}
    routine.script.extend([generator])
    r2 = agent.handle_event(ev("generate_initial", {"target_question_ids": ["q1", "q2"]}, expected=rev))
    assert r2["status"] == "ready" and len(routine.calls) == 3  # q1 reused from cache, only q2 regenerated


def test_crash_mid_batch_resumes_same_event_without_repeating_paid_work(env):
    agent, routine, _ = env
    rev = prepared(agent)

    def boom(system, user):
        raise RuntimeError("process died")

    routine.script.clear()
    routine.script.extend([generator, boom])
    e = ev("generate_initial", {"target_question_ids": ["q1", "q2"]}, expected=rev)
    with pytest.raises(RuntimeError):
        agent.handle_event(e)
    assert agent._repo("s1").session_usage("f1")["uncertain"] == 1
    routine.script.extend([generator])
    r = agent.handle_event(e)  # same event_id: resumes from the checkpoint before `generate`
    assert r["status"] == "ready" and len(routine.calls) == 3
    assert len(agent._repo("s1").candidates("f1", "q1")) == 2
