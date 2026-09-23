import io
import json
from pathlib import Path

import pytest

from answer_cache_agent import harness
from answer_cache_agent.ingest import ingest

FIX = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.parametrize("domain", ["personal_application", "org_questionnaire"])
def test_ingest_fixture_counts_and_index(domain, tmp_path):
    repo = harness.open_repository(str(tmp_path / "k.db"), domain, hash_embedder=True)
    with open(FIX / domain / "knowledge.jsonl", encoding="utf-8") as fh:
        counts = ingest(repo, fh)
    assert counts["template"] >= 5 and counts["evidence"] >= 3 and counts["variable"] >= 2
    n_vec = repo.conn.execute("SELECT COUNT(*) FROM vec_items WHERE scope_id=?", (domain,)).fetchone()[0]
    assert n_vec == counts["template"] + counts["evidence"]


def test_ingest_rejects_unapproved_template_with_line_number(tmp_path):
    repo = harness.open_repository(str(tmp_path / "k.db"), "s", hash_embedder=True)
    bad = ['{"kind":"dimension","id":"d","label":"D"}',
           '{"kind":"template","id":"T","intent":"x","body":"b","disclosure":"model_visible"}']
    with pytest.raises(ValueError, match="line 2"):
        ingest(repo, bad)
    assert repo.template("T") is None


@pytest.mark.parametrize("domain", ["personal_application", "org_questionnaire"])
def test_demo_runs_offline_with_success_marker(domain, tmp_path, capsys):
    rc = harness.main(["--demo", domain, "--db", str(tmp_path / "demo.db")])
    out = capsys.readouterr().out
    assert rc == 0 and harness.SUCCESS_MARKER in out
    lines = [json.loads(l) for l in out.splitlines() if l.startswith("{")]
    assert lines[0]["event"] == "prepare_form" and lines[0]["usage"]["calls"] == 0
    assert lines[1]["event"] == "generate_initial" and lines[1]["candidates"]


def test_personal_demo_abstains_on_unsupported_question_and_reuses_cache(tmp_path):
    agent = harness.build_agent(str(tmp_path / "p.db"), fake=True, hash_embedder=True,
                                bindings=json.load(open(FIX / "personal_application/bindings.json")), routine=None, advanced=None)
    with open(FIX / "personal_application/knowledge.jsonl", encoding="utf-8") as fh:
        ingest(agent._repo("personal_application"), fh)
    events = [json.loads(l) for l in open(FIX / "personal_application/events.jsonl") if l.strip()]
    res = harness.run_script(agent, events, "personal_application", "sess", out=io.StringIO())
    by_type = {}
    for e, r in zip(events, res):
        by_type.setdefault(e["type"], []).append(r)
    gen = by_type["generate_initial"][0]
    assert gen["status"] == "partial" and {u["question_id"]: u["reason"] for u in gen["unresolved"]} == {"q4": "insufficient_evidence"}
    assert {c["question_id"] for c in gen["candidates"]} == {"q1"} and set(gen["cached"]) == {"q2", "q3"}
    concise = by_type["get_candidate"][0]
    assert concise["candidates"][0]["variant"] == "concise" and concise["usage"]["calls"] == gen["usage"]["calls"]
    regen = by_type["regenerate_question"][0]
    assert regen["status"] == "ready" and 1 <= len(regen["candidates"]) <= 5 and "wrong_emphasis" in regen["candidates"][0]["body"]
    assert all(r["status"] == "ready" for r in by_type["record_feedback"])
    assert agent._repo("personal_application").template("T_strength_eval_v2")["origin_candidate_id"] == regen["candidates"][0]["id"]


def test_org_demo_requires_filter_and_overlong_after_substitution(tmp_path):
    agent = harness.build_agent(str(tmp_path / "o.db"), fake=True, hash_embedder=True,
                                bindings=json.load(open(FIX / "org_questionnaire/bindings.json")), routine=None, advanced=None)
    with open(FIX / "org_questionnaire/knowledge.jsonl", encoding="utf-8") as fh:
        ingest(agent._repo("org_questionnaire"), fh)
    events = [json.loads(l) for l in open(FIX / "org_questionnaire/events.jsonl") if l.strip()]
    res = harness.run_script(agent, events, "org_questionnaire", "sess", out=io.StringIO())
    gen, s3, s5 = res[1], res[4], res[5]
    s2 = [c for c in gen["candidates"] if c["question_id"] == "s2"]
    assert s2 and all(c["template_refs"] == ["T_incident_enterprise"] for c in s2)  # enterprise context beats smb
    assert s3["candidates"] and "{{dpo_email}}" in s3["candidates"][0]["body"]  # requires region=eu satisfied
    assert s5["status"] == "partial" and s5["candidates"] == []  # s5: 80-char limit fails once names/dates substituted
    invalid = agent._repo("org_questionnaire").candidates("sess", "s5", statuses=("invalid",))
    assert invalid and any("length" in p for p in invalid[0]["validation"]["problems"])
