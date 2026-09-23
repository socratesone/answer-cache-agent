"""Evaluation report (PRD §13): retrieval, contextual ranking, learning vs fixed baseline, abstention, constraints, reuse, usage.

Offline by default (hash embedder + scripted provider). `--real` uses the fastembed model for the retrieval sections.
Writes Markdown to --out (default docs/evaluation-report.md).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from answer_cache_agent import harness  # noqa: E402
from answer_cache_agent.config import load_config  # noqa: E402
from answer_cache_agent.ingest import ingest  # noqa: E402

FIX = ROOT / "fixtures"
DOMAINS = ["personal_application", "org_questionnaire"]


def _agent(domain: str, real: bool, tmp: Path):
    a = harness.build_agent(str(tmp / f"{domain}.db"), fake=True, hash_embedder=not real,
                            bindings=json.load(open(FIX / domain / "bindings.json")), routine=None, advanced=None)
    with open(FIX / domain / "knowledge.jsonl", encoding="utf-8") as fh:
        ingest(a._repo(domain), fh)
    return a


def _bundle(agent, domain, query, context):
    return agent._bundle(agent._repo(domain), {"id": "q", "text": query, "constraints": {}, "prefilled": False, "hints": []},
                         {"state": {"values": context}}, [])


def retrieval_and_ranking(agent, domain) -> dict:
    cases = [json.loads(l) for l in open(FIX / domain / "eval_cases.jsonl") if l.strip()]
    repo = agent._repo(domain)
    hit1 = hit3 = top1 = 0
    rows = []
    for cs in cases:
        raw = [t for t, _ in repo.search(cs["query"], "template", 3)]
        intents = [repo.template(t)["intent"] for t in raw]
        hit1 += intents[:1] == [cs["expect_intent"]]
        hit3 += cs["expect_intent"] in intents
        ranked = [t["id"] for t in _bundle(agent, domain, cs["query"], cs["context"])["templates"]]
        expect = cs["expect_top"] if isinstance(cs["expect_top"], list) else [cs["expect_top"]]
        top1 += bool(ranked) and ranked[0] in expect
        rows.append((cs["query"], json.dumps(cs["context"]), raw[0] if raw else "-", ranked[0] if ranked else "-", " / ".join(expect)))
    return {"n": len(cases), "hit@1": hit1, "hit@3": hit3, "context_top1": top1, "rows": rows}


def learning_vs_baseline(agent, domain) -> dict:
    """Select the same-intent runner-up 5x in context X; confirm it rises in X (learning on), not with learning off, and not in Y."""
    cases = [json.loads(l) for l in open(FIX / domain / "eval_cases.jsonl") if l.strip()]
    repo = agent._repo(domain)
    cs = target = None
    for cand in cases:
        if not cand["context"]:
            continue
        ranked = _bundle(agent, domain, cand["query"], cand["context"])["templates"]
        leader_intent = repo.template(ranked[0]["id"])["intent"] if ranked else None
        same = [t["id"] for t in ranked[1:] if repo.template(t["id"])["intent"] == leader_intent]
        if same:
            cs, target = cand, same[0]
            break
    if cs is None:
        return {"skipped": "no case with two eligible templates of the same intent"}
    ranked = _bundle(agent, domain, cs["query"], cs["context"])["templates"]
    before = [t["id"] for t in ranked]
    score_before = {t["id"]: t["ranking"]["score"] for t in ranked}
    other = {d: [v for v in vals] for d, vals in cs["context"].items()}
    flat = {v for vals in cs["context"].values() for v in vals}
    repo.save_session("eval", "r", {})
    repo.add_candidate(dict(id="eval-c", session_id="eval", question_id="q", batch_id="b", variant="standard", body="x",
                            template_refs=[target], prompt_version="p", model_id="m", form_revision="r", status="valid"))
    for i in range(5):
        repo.record_feedback(f"eval-{i}", "eval-c", "selected", [], None, flat, agent.cfg.ranking)
    on = _bundle(agent, domain, cs["query"], cs["context"])["templates"]
    after_on = [t["id"] for t in on]
    score_on = {t["id"]: t["ranking"]["score"] for t in on}
    comp = next(t["ranking"] for t in on if t["id"] == target)
    # unrelated context: swap every value for a sibling value in the same dimension when one exists
    unrelated = {}
    for d, vals in other.items():
        siblings = [r[0] for r in repo.conn.execute("SELECT id FROM value_ WHERE scope_id=? AND dimension_id=? AND id NOT IN (%s)"
                                                    % ",".join("?" * len(vals)), (repo.scope, d, *vals))]
        if siblings:
            unrelated[d] = siblings[:1]
    y_on = [(t["id"], t["ranking"]["score"]) for t in _bundle(agent, domain, cs["query"], unrelated)["templates"]] if unrelated else []
    agent.cfg.ranking.learning_enabled = False
    after_off = [t["id"] for t in _bundle(agent, domain, cs["query"], cs["context"])["templates"]]
    y_off = [(t["id"], t["ranking"]["score"]) for t in _bundle(agent, domain, cs["query"], unrelated)["templates"]] if unrelated else []
    agent.cfg.ranking.learning_enabled = True
    return {"query": cs["query"], "context": cs["context"], "target": target, "before": before, "after_learning_on": after_on,
            "after_learning_off": after_off, "unrelated_context": unrelated, "ranking_in_unrelated": [i for i, _ in y_on],
            "target_pref_component": comp["preference"], "pref_key": comp["preference_key"],
            "target_score_before": score_before[target], "target_score_after": score_on[target],
            "leader_score": score_before[before[0]],
            "rose_in_context": after_on.index(target) < before.index(target),
            "unchanged_with_learning_off": after_off == before,
            "unchanged_in_unrelated": [i for i, _ in y_on] == [i for i, _ in y_off]}


def scenario_run(agent, domain) -> dict:
    events = [json.loads(l) for l in open(FIX / domain / "events.jsonl") if l.strip()]
    res = harness.run_script(agent, events, domain, f"eval-{uuid.uuid4()}", out=io.StringIO())
    repo = agent._repo(domain)
    sess = [r for r in res if r["revision"]][0]
    session_id = repo.conn.execute("SELECT id FROM form_session WHERE revision=? ORDER BY updated_at DESC", (sess["revision"],)).fetchone()[0]
    all_c = repo.candidates(session_id, statuses=("valid", "invalid", "unevaluated", "stale", "needs_information"))
    by_status = {}
    for cd in all_c:
        by_status[cd["status"]] = by_status.get(cd["status"], 0) + 1
    problems = [p for cd in all_c for p in cd["validation"].get("problems", [])]
    unresolved = {}
    for r in res:
        for u in r["unresolved"]:
            unresolved[u["reason"]] = unresolved.get(u["reason"], 0) + 1
    calls_by_event = [(r_ev["type"], r["usage"]["calls"]) for r_ev, r in zip(events, res)]
    reuse_hits = sum(1 for e, r in zip(events, res) if e["type"] == "get_candidate" and r["candidates"])
    shown = {r[0] for r in repo.conn.execute("SELECT candidate_id FROM exposure")}
    pregen_unused = sum(1 for cd in all_c if cd["status"] == "valid" and cd["id"] not in shown)
    unsupported = sum(1 for cd in all_c if cd["status"] == "valid" and not (cd["evidence_refs"] or cd["template_refs"]))
    return {"statuses": [r["status"] for r in res], "candidates_by_status": by_status, "validation_problems": problems,
            "unresolved_by_reason": unresolved, "paid_calls_after_each_event": calls_by_event, "get_candidate_cache_hits": reuse_hits,
            "valid_candidates_never_shown": pregen_unused, "valid_without_any_reference": unsupported, "usage": res[-1]["usage"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--real", action="store_true", help="use the fastembed model for retrieval sections")
    p.add_argument("--out", default=str(ROOT / "docs" / "evaluation-report.md"))
    a = p.parse_args(argv)
    import tempfile
    cfg = load_config()
    lines = [f"# Evaluation Report", "",
             f"_Generated {datetime.now(timezone.utc).date()} by `scripts/evaluate.py`"
             f"{' --real' if a.real else ''}. Embedder: {'fastembed ' + cfg.retrieval.embedding_model if a.real else 'HashEmbedder (lexical, offline)'}; "
             f"provider: scripted demo model (no network). Fixtures are synthetic (`fixtures/`). Ranking policy version {cfg.ranking.policy_version}._", ""]
    with tempfile.TemporaryDirectory() as tmp:
        for domain in DOMAINS:
            agent = _agent(domain, a.real, Path(tmp))
            rr = retrieval_and_ranking(agent, domain)
            lv = learning_vs_baseline(agent, domain)
            sc = scenario_run(agent, domain)
            lines += [f"## {domain}", "", "### Retrieval relevance and contextual ranking", "",
                      f"- Raw semantic hit@1 (intent): **{rr['hit@1']}/{rr['n']}**; hit@3: **{rr['hit@3']}/{rr['n']}**",
                      f"- Correct top template after `requires` filter + context ranking: **{rr['context_top1']}/{rr['n']}**", "",
                      "| Query | Context | Raw top | Ranked top | Expected |", "|---|---|---|---|---|"]
            lines += [f"| {q} | `{c}` | {r} | {k} | {e} |" for q, c, r, k, e in rr["rows"]]
            lines += ["", "### Feedback-adjusted ranking vs fixed baseline", ""]
            if "skipped" in lv:
                lines.append(f"- Skipped: {lv['skipped']}")
            else:
                lines += [f"- Query `{lv['query']}` in context `{json.dumps(lv['context'])}`; runner-up `{lv['target']}` selected 5×.",
                          f"- Baseline order: `{lv['before']}`",
                          f"- Learning on: `{lv['after_learning_on']}` → rose in context: **{lv['rose_in_context']}** "
                          f"(preference component {lv['target_pref_component']:.3f} at key `{lv['pref_key']}`; "
                          f"target score {lv['target_score_before']:.3f} → {lv['target_score_after']:.3f} vs leader {lv['leader_score']:.3f}; "
                          f"maximum preference shift is bounded at {cfg.ranking.weights.preference * (1 - cfg.ranking.alpha / (cfg.ranking.alpha + cfg.ranking.beta)):.3f})",
                          f"- Learning off (fixed baseline, same events recorded): `{lv['after_learning_off']}` → unchanged: **{lv['unchanged_with_learning_off']}**",
                          f"- Unrelated context `{json.dumps(lv['unrelated_context'])}`: `{lv['ranking_in_unrelated']}` → identical with learning on and off (no spill-over): **{lv['unchanged_in_unrelated']}**"]
            lines += ["", "### Scenario run (fixture events, scripted provider)", "",
                      f"- Statuses per event: `{sc['statuses']}`",
                      f"- Candidates by status: `{sc['candidates_by_status']}`; valid candidates with no evidence/template reference: **{sc['valid_without_any_reference']}**",
                      f"- Validation problems (constraint compliance after substitution): `{sc['validation_problems']}`",
                      f"- Abstentions / unresolved by reason: `{sc['unresolved_by_reason']}`",
                      f"- Paid calls (cumulative) after each event: `{sc['paid_calls_after_each_event']}`",
                      f"- `get_candidate` served from cache without a call: **{sc['get_candidate_cache_hits']}**; pre-generated valid candidates never shown: **{sc['valid_candidates_never_shown']}**",
                      f"- Session usage: `{sc['usage']}`", ""]
    lines += ["## Reading this report", "",
              "- The scripted provider always cites the top-ranked bundle item and never invents, so *supported vs unsupported* here measures the "
              "deterministic evidence-linkage gate, not a real model's honesty. Run with real providers to measure that.",
              "- Abstention on the unsupported question is driven by retrieval returning nothing above `retrieval.min_similarity`; with the real "
              "embedder unrelated questions still score ~0.5–0.6, so abstention there depends on the generator (documented limitation, Q5/Q6).",
              "- Learning is bounded: the preference component's weight is capped by config; the report shows it moving a runner-up, not overriding "
              "filters. 'Rose in context' with 'no spill-over' is the specified behavior, not a claim of generalized improvement.",
              "- Numbers are on a six-case synthetic set per domain. Benchmark size and numerical targets remain a review item (PRD §13)."]
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
