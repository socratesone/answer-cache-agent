from datetime import datetime, timezone

import pytest

from answer_cache_agent.config import load_config
from answer_cache_agent.db import connect, init_schema
from answer_cache_agent.embeddings import HashEmbedder
from answer_cache_agent.ranking import ctx_match, preference, requires_satisfied, score
from answer_cache_agent.repository import Repository
from answer_cache_agent.vectors import SqliteVecStore

CFG = load_config()
APPROVED = dict(disclosure="model_visible", approved_by="user", approved_at="2026-09-01")


@pytest.fixture
def repo(tmp_path):
    emb = HashEmbedder()
    conn = connect(tmp_path / "t.db")
    init_schema(conn, emb.model_id, emb.dim)
    r = Repository(conn, "s1", emb, SqliteVecStore(conn))
    r.add_dimension("role_family", "Role family")
    r.add_value("full_stack", "role_family", "Full stack")
    r.add_value("agent_engineering", "role_family", "Agent engineering")
    r.add_dimension("sector", "Sector")
    r.add_value("education", "sector", "Education")
    r.add_evidence("E3", "https://example.org/blog", "2026-08", "We ship evaluation tooling with agents.", **APPROVED)
    r.add_variable("v17", "User-approved motivation statement", "text", "verbatim")
    r.add_intent_alias("motivation", "Why do you want to work here?")
    r.add_intent_alias("motivation", "Why are you interested in this organization?")
    for tid, ctx in (("A", "full_stack"), ("B", "agent_engineering"), ("C", "education")):
        r.add_template(tid, "motivation", f"{{{{v17}}}} Template {tid}.", ["v17"], ["E3"], **APPROVED)
        r.assign("template", tid, ctx)
    r.add_intent_alias("salary", "What are your salary expectations?")
    r.add_template("S", "salary", "Negotiable based on scope.", [], [], **APPROVED)
    return r


def test_paraphrase_retrieval_and_scope_isolation(repo):
    hits = repo.search("why do you want to work at this organization", "template", 5)
    assert [h[0] for h in hits][:3] and set(h[0] for h in hits[:3]) == {"A", "B", "C"}
    assert hits[0][1] > 0.3
    other = Repository(repo.conn, "s2", repo.embedder, repo.store)
    assert other.search("why do you want to work here", "template", 5) == []


def test_context_changes_ranking(repo):
    form = {"role_family": {"agent_engineering"}, "sector": {"education"}}
    ranked = sorted(
        ("A", "B", "C"),
        key=lambda t: -score(0.9, ctx_match(repo.template(t)["applies"], form), 0.5, 0.5, CFG.ranking)["score"])
    assert ranked[-1] == "A"
    assert requires_satisfied(repo.template("A")["requires"], form)


def test_requires_is_a_hard_filter(repo):
    repo.assign("template", "C", "education", mode="requires")
    assert not requires_satisfied(repo.template("C")["requires"], {"role_family": {"full_stack"}})
    assert requires_satisfied(repo.template("C")["requires"], {"sector": {"education"}})


def test_feedback_is_exactly_once_and_backs_off(repo):
    repo.save_session("f1", "r1", {})
    repo.add_candidate(dict(id="c1", session_id="f1", question_id="q1", batch_id="b1", variant="standard",
                            body="x", template_refs=["B"], prompt_version="p1", model_id="m", form_revision="r1", status="valid"))
    ctx = {"agent_engineering", "education"}
    assert repo.record_feedback("e1", "c1", "selected", [], None, ctx, CFG.ranking)
    assert not repo.record_feedback("e1", "c1", "selected", [], None, ctx, CFG.ranking)
    now = datetime.now(timezone.utc)
    assert repo.stats("B", "agent_engineering|education").sel == 1
    assert repo.stats("B", "*").sel == 1
    p, key = preference(lambda k: repo.stats("B", k), ctx, now, CFG.ranking)
    assert key == "prior" and p == 0.5  # n=1 < min_n=3 and a known context never falls through to global
    p, key = preference(lambda k: repo.stats("B", k), set(), now, CFG.ranking)
    assert key == "*" and 0.5 < p < 1.0  # only a context-free form consults the global key


def test_exposure_does_not_imply_rejection(repo):
    repo.record_exposure("e2", ["c1"], ["c2"], {})
    assert repo.stats("c2", "*") is None


def test_stale_revision_invalidates(repo):
    repo.add_candidate(dict(id="c9", session_id="f2", question_id="q1", batch_id="b", variant="standard", body="x",
                            prompt_version="p", model_id="m", form_revision="r1", status="valid"))
    assert repo.mark_stale("f2", "r2") == 1
    assert repo.candidates("f2", "q1") == []
    assert repo.candidates("f2", "q1", statuses=("stale",))[0]["id"] == "c9"


def test_ledger_uncertain_counts_at_estimate(repo):
    repo.reserve_call("k1", "e5", "f3", "routine", "m", 1000, 400)
    repo.reserve_call("k2", "e5", "f3", "routine", "m", 1000, 400)
    repo.confirm_call("k1", 900, 300, 0.01)
    repo.mark_uncertain("k2")
    u = repo.session_usage("f3")
    assert u == {"calls": 2, "tokens": 1200 + 1400, "cost_usd": 0.01, "uncertain": 1}
    assert repo.uncertain_calls("e5") == ["k2"]


def test_event_replay_returns_stored_result(repo):
    repo.record_event("e7", "f1", "get_candidate", {"status": "ready"})
    repo.record_event("e7", "f1", "get_candidate", {"status": "different"})
    assert repo.event_result("e7") == {"status": "ready"}


def test_promotion_keeps_provenance_and_never_creates_evidence(repo):
    repo.add_candidate(dict(id="c3", session_id="f1", question_id="q1", batch_id="b", variant="concise", body="{{v17}} short.",
                            variables=["v17"], evidence_refs=["E3"], prompt_version="p", model_id="m", form_revision="r1", status="valid"))
    repo.promote_candidate("c3", "T_new", "user", "2026-09-21")
    t = repo.template("T_new")
    assert t["origin_candidate_id"] == "c3" and t["evidence_ids"] == ["E3"]
    assert repo.evidence(["c3", "T_new"]) == []


def test_reindex_required_on_model_change(tmp_path):
    conn = connect(tmp_path / "m.db")
    init_schema(conn, "hash-64", 64)
    with pytest.raises(RuntimeError, match="reindex required"):
        init_schema(conn, "other", 64)
