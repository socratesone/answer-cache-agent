"""The four-node LangGraph agent and its event entrypoint.

Prepare/Retrieve -> Generate -> Evaluate -> Persist/Learn, routed per event type. State holds bounded
working context and record references only; bindings, credentials, and adapters live on the Agent
object (closures), never in graph state or checkpoints.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from answer_cache_agent import contracts as c
from answer_cache_agent.budget import PaidCallGate
from answer_cache_agent.config import Config, load_config
from answer_cache_agent.db import connect, init_schema
from answer_cache_agent.embeddings import Embedder, FastEmbedEmbedder
from answer_cache_agent.prompts import load_prompt
from answer_cache_agent.providers import Credentials, ModelRoles, ProviderAdapter, build_adapter
from answer_cache_agent.ranking import ctx_match, preference, requires_satisfied, score
from answer_cache_agent.rendering import check_constraints, render, unauthorized_variables
from answer_cache_agent.repository import Repository
from answer_cache_agent.vectors import SqliteVecStore

GENERATING = {"generate_initial", "regenerate_question"}
INITIAL_VARIANTS = ("standard", "concise")
MAX_TARGETED = 5


@dataclass
class RuntimeDeps:
    """Trusted runtime inputs. Nothing here is ever serialized into state, checkpoints, or model payloads."""
    db_path: str
    credentials: Credentials = field(default_factory=Credentials)
    model_roles: ModelRoles | None = None
    bindings: Mapping[str, str] = field(default_factory=dict)
    config_path: str | None = None
    embedder: Embedder | None = None
    adapters: dict[str, ProviderAdapter] | None = None


class AgentState(TypedDict, total=False):
    event: dict
    payload: dict
    session: dict
    targets: list[str]
    immediate: list[str]
    bundles: dict
    diagnosis: dict | None
    unresolved: list[dict]
    diagnostics: list[str]
    status: str | None
    result: dict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _revision(payload: dict) -> str:
    return "rev-" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


class Agent:
    """One per host process. `handle_event` is the whole public runtime surface."""

    def __init__(self, runtime: RuntimeDeps) -> None:
        self.rt = runtime
        self.cfg: Config = load_config(runtime.config_path)
        self.embedder = runtime.embedder or FastEmbedEmbedder(self.cfg.retrieval.embedding_model)
        self.conn = connect(runtime.db_path)
        init_schema(self.conn, self.embedder.model_id, self.embedder.dim)
        self.store = SqliteVecStore(self.conn)
        ckpt_conn = sqlite3.connect(runtime.db_path, check_same_thread=False)
        self.checkpointer = SqliteSaver(ckpt_conn)
        self.graph = self._build()

    # -- public ------------------------------------------------------------------------------
    def handle_event(self, event: dict) -> dict:
        ev = c.Event.model_validate(event)
        repo = self._repo(ev.scope_id)
        replay = repo.event_result(ev.event_id)
        if replay is not None:
            return replay
        evd = ev.model_dump()
        try:
            payload = c.parse_payload(ev).model_dump()
        except Exception as exc:
            return self._finish(repo, evd, c.Result(event_id=ev.event_id, status="failed", revision=None, diagnostics=[f"invalid payload: {exc}"]))
        session = repo.session(ev.session_id)
        if ev.type == "prepare_form" and session is None:
            pass
        elif session is None:
            return self._finish(repo, evd, c.Result(event_id=ev.event_id, status="failed", revision=None, diagnostics=["unknown session; send prepare_form first"]))
        elif ev.expected_revision != session["revision"]:
            return c.Result(event_id=ev.event_id, status="stale_context", revision=session["revision"],
                            diagnostics=[f"expected_revision {ev.expected_revision} != {session['revision']}"]).model_dump()
        config = {"configurable": {"thread_id": f"{ev.scope_id}/{ev.session_id}"}}  # session ids are per scope
        snap = self.graph.get_state(config)
        resume = bool(snap.next) and snap.values.get("event", {}).get("event_id") == ev.event_id
        initial: AgentState = {"event": evd, "payload": payload, "session": session or {}, "targets": [], "immediate": [],
                               "bundles": {}, "diagnosis": None, "unresolved": [], "diagnostics": [], "status": None, "result": {}}
        out = self.graph.invoke(None if resume else initial, config)
        return out["result"]

    # -- graph -------------------------------------------------------------------------------
    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("prepare", self.prepare)
        g.add_node("generate", self.generate)
        g.add_node("evaluate", self.evaluate)
        g.add_node("persist", self.persist)
        g.add_conditional_edges(START, lambda s: "persist" if s["event"]["type"] == "record_feedback" else "prepare")
        g.add_conditional_edges("prepare", lambda s: "generate" if s["event"]["type"] in GENERATING and not s.get("status") else "persist")
        g.add_edge("generate", "evaluate")
        g.add_edge("evaluate", "persist")
        g.add_edge("persist", END)
        return g.compile(checkpointer=self.checkpointer)

    def _repo(self, scope_id: str) -> Repository:
        return Repository(self.conn, scope_id, self.embedder, self.store)

    def _adapter(self, role: str) -> ProviderAdapter:
        if self.rt.adapters:
            return self.rt.adapters[role]
        if self.rt.model_roles is None:
            raise RuntimeError("model_roles not configured")
        return build_adapter(self.rt.model_roles.get(role), self.rt.credentials)

    # -- node 1: prepare / retrieve ------------------------------------------------------------
    def prepare(self, s: AgentState) -> dict:
        ev, payload, repo = s["event"], s["payload"], self._repo(s["event"]["scope_id"])
        diagnostics: list[str] = []
        if ev["type"] in ("prepare_form", "update_form"):
            revision = _revision(payload)
            values = self._form_values(payload, diagnostics)
            session = {"id": ev["session_id"], "revision": revision,
                       "state": {**payload, "values": {d: sorted(v) for d, v in values.items()}, "updated_at": _now()}}
            repo.save_session(ev["session_id"], revision, session["state"])
            stale = repo.mark_stale(ev["session_id"], revision)
            if stale:
                diagnostics.append(f"{stale} cached candidates marked stale by revision change")
            return {"session": session, "diagnostics": diagnostics}

        session = s["session"]
        if ev["type"] not in GENERATING:
            return {}
        questions = {q["id"]: q for q in session["state"]["questions"]}
        if ev["type"] == "generate_initial":
            wanted = list(dict.fromkeys(payload["target_question_ids"] + payload["authorized_question_ids"]))
            wanted = wanted[: min(self.cfg.batch.max_questions_per_batch, payload["limits"].get("max_questions") or 10**9)]
            immediate = [q for q in payload["target_question_ids"] if q in wanted]
        else:
            wanted, immediate = [payload["question_id"]], [payload["question_id"]]
        targets, unresolved = [], []
        for qid in wanted:
            q = questions.get(qid)
            if q is None:
                unresolved.append({"question_id": qid, "reason": "out_of_scope", "needed": "question not in form"})
            elif q["prefilled"] and qid not in payload.get("target_question_ids", [payload.get("question_id")]):
                diagnostics.append(f"{qid} prefilled; skipped")
            else:
                targets.append(qid)
        bundles = {qid: self._bundle(repo, questions[qid], session, unresolved) for qid in targets}
        return {"targets": targets, "immediate": immediate, "bundles": bundles, "unresolved": unresolved, "diagnostics": diagnostics}

    def _form_values(self, payload: dict, diagnostics: list[str]) -> dict[str, set[str]]:
        """Deterministic only (Q2): caller/user hints plus user-defined regex rules."""
        values: dict[str, set[str]] = {}
        for h in payload["hints"]:
            values.setdefault(h["dimension"], set()).add(h["value"])
        fields = {"page_url": payload.get("page_url") or "", "page_title": payload.get("page_title") or "",
                  "question_text": "\n".join(q["text"] for q in payload["questions"])}
        for r in payload["rules"]:
            try:
                if re.search(r["pattern"], fields[r["match_field"]]):
                    values.setdefault(r["dimension"], set()).add(r["value"])
            except re.error as exc:
                diagnostics.append(f"rule {r['id']} invalid regex: {exc}")
        return values

    def _bundle(self, repo: Repository, q: dict, session: dict, unresolved: list[dict]) -> dict:
        form = {d: set(v) for d, v in session["state"]["values"].items()}
        for h in q.get("hints", []):
            form.setdefault(h["dimension"], set()).add(h["value"])
        flat = {v for vals in form.values() for v in vals}
        now = datetime.now(timezone.utc)
        k, floor = self.cfg.retrieval.top_k, self.cfg.retrieval.min_similarity
        hits = [(tid, sim) for tid, sim in repo.search(q["text"], "template", k) if sim >= floor]
        # Raw cosine gaps between neighbours are narrow; min-max normalise so the semantic component can discriminate.
        lo, hi = (min(s for _, s in hits), max(s for _, s in hits)) if hits else (0.0, 0.0)
        templates = []
        for tid, sim in hits:
            t = repo.template(tid)
            if t is None or t["status"] != "approved" or t["disclosure"] != "model_visible" or not requires_satisfied(t["requires"], form):
                continue
            pref, key = preference(lambda key: repo.stats(tid, key), flat, now, self.cfg.ranking)
            # A required value is also the strongest applicability signal; it counts toward context match.
            applies = {d: t["applies"].get(d, set()) | t["requires"].get(d, set()) for d in set(t["applies"]) | set(t["requires"])}
            sem = (sim - lo) / (hi - lo) if hi > lo else 1.0
            comp = score(sem, ctx_match(applies, form), 0.5, pref, self.cfg.ranking)
            comp.update({"semantic_raw": sim, "preference_key": key})
            templates.append({"id": tid, "body": t["body"], "variables": t["variables"], "evidence_ids": t["evidence_ids"], "ranking": comp})
        templates.sort(key=lambda t: -t["ranking"]["score"])
        evidence = [e for eid, sim in repo.search(q["text"], "evidence", k) if sim >= floor for e in repo.evidence([eid])
                    if e["disclosure"] == "model_visible" and e["revoked_at"] is None]
        variables = repo.variables()
        bundle = {"question": q, "context_values": {d: sorted(v) for d, v in form.items()}, "templates": templates,
                  "evidence": [{"id": e["id"], "excerpt": e["excerpt"], "version": e["version"]} for e in evidence],
                  "variables": [{"id": v["id"], "safe_description": v["safe_description"], "value_type": v["value_type"],
                                 "permitted_use": v["permitted_use"]} for v in variables]}
        if not templates and not evidence:
            unresolved.append({"question_id": q["id"], "reason": "insufficient_evidence",
                               "needed": "an approved template or evidence record relevant to this question"})
            bundle["gap"] = "insufficient_evidence"
        return bundle

    # -- node 2: generate ------------------------------------------------------------------------
    def generate(self, s: AgentState) -> dict:
        ev, payload, repo = s["event"], s["payload"], self._repo(s["event"]["scope_id"])
        session, bundles = s["session"], s["bundles"]
        unresolved, diagnostics = list(s["unresolved"]), list(s["diagnostics"])
        gate = PaidCallGate(repo, self.cfg, ev["session_id"], ev["event_id"], c.RequestLimits(**payload.get("limits", {})), self.rt.bindings)
        batch_id = ev["event_id"]
        diagnosis = None

        if ev["type"] == "regenerate_question":
            qid = payload["question_id"]
            targeted = self._targeted_batches(repo, ev["session_id"], qid)
            rejected = self._rejections(repo, ev["session_id"], qid, payload["rejected"])
            latest = targeted[-1] if targeted else []
            exhausted = bool(latest) and all(cid in rejected for cid in latest)
            if exhausted:
                reasons_present = any(r["reasons"] or r["free_text"] for cid, r in rejected.items() if cid in latest)
                if not reasons_present:
                    return {"status": "needs_feedback", "unresolved": unresolved + [{"question_id": qid, "reason": "set_exhausted",
                            "needed": "structured rejection reasons or notes for the rejected candidates"}], "diagnostics": diagnostics}
                if len(targeted) >= self.cfg.generation.max_regen_rounds_before_feedback:
                    return {"status": "needs_feedback", "unresolved": unresolved + [{"question_id": qid, "reason": "set_exhausted",
                            "needed": f"{len(targeted)} targeted rounds exhausted; more information or a manual answer"}], "diagnostics": diagnostics}
                if self.cfg.evaluator.enabled:
                    diagnosis = self._diagnose(gate, bundles[qid], repo, latest, rejected, diagnostics)
            shown = [cid for cid in self._shown(repo, ev["session_id"], qid)]
            mode, targets = "targeted", [qid]
        else:
            mode, targets, shown, rejected = "initial", s["targets"], [], {}

        for qid in targets:
            bundle = bundles[qid]
            if bundle.get("gap"):
                continue
            if mode == "initial" and repo.candidates(ev["session_id"], qid, statuses=("valid", "unevaluated")):
                diagnostics.append(f"{qid} already has cached candidates; skipped")
                continue
            if mode == "targeted" and any(cd["batch_id"] == batch_id for cd in repo.candidates(ev["session_id"], qid, statuses=("valid", "unevaluated", "invalid"))):
                continue  # resumed run: this question's batch was already written through
            r = self._generate_one(gate, mode, bundle, repo, shown, rejected, diagnosis)
            if r.status != "ok":
                reason = "budget_exhausted" if r.meta.get("budget_refused") else "provider_failed"
                unresolved.append({"question_id": qid, "reason": reason, "needed": r.error or r.status})
                diagnostics.append(f"{qid}: provider {r.status}: {r.error or r.raw_text[:80]}")
                if reason == "budget_exhausted":
                    break
                continue
            try:
                out = c.GenerationOutput.model_validate(r.data)
            except Exception as exc:
                unresolved.append({"question_id": qid, "reason": "provider_failed", "needed": f"schema-invalid output: {exc}"[:200]})
                continue
            for ab in out.abstentions:
                unresolved.append({"question_id": ab.question_id, "reason": ab.reason, "needed": ab.needed})
            items = [it for it in out.items if it.question_id == qid]
            if mode == "targeted":
                items = [it for it in items if it.variant == "alternative"][:MAX_TARGETED]
            for it in items:
                repo.add_candidate(dict(id=str(uuid.uuid4()), session_id=ev["session_id"], question_id=qid, batch_id=batch_id,
                                        variant=it.variant, body=it.body, variables=it.variables, evidence_refs=it.evidence_refs,
                                        template_refs=it.template_refs, prompt_version=load_prompt(mode if mode == "initial" else "targeted")[0],
                                        model_id=r.model_id, form_revision=session["revision"], status="unevaluated",
                                        self_report=it.self_report.model_dump(),
                                        validation={"ranking": next((t["ranking"] for t in bundle["templates"] if t["id"] in it.template_refs), None)}))
        diagnostics += gate.diagnostics
        return {"unresolved": unresolved, "diagnostics": diagnostics, "diagnosis": diagnosis}

    def _generate_one(self, gate, mode, bundle, repo, shown, rejected, diagnosis):
        version, system = load_prompt("initial" if mode == "initial" else "targeted")
        user = {"CONTEXT BUNDLE": {"question": bundle["question"], "context_values": bundle["context_values"],
                                   "templates": [{k: t[k] for k in ("id", "body", "variables", "evidence_ids")} for t in bundle["templates"]],
                                   "evidence": bundle["evidence"]},
                "PERMITTED VARIABLES": bundle["variables"]}
        if mode == "initial":
            user["TARGET QUESTIONS"] = [bundle["question"]["id"]]
            n = 2
        else:
            user["MAX_CANDIDATES"] = MAX_TARGETED
            user["PREVIOUSLY SHOWN"] = [{"id": cid, "body": (repo.candidate(cid) or {}).get("body")} for cid in shown]
            user["REJECTED"] = [{"id": cid, **r} for cid, r in rejected.items()]
            user["DIAGNOSIS"] = diagnosis
            n = MAX_TARGETED
        max_out = min(self.cfg.generation.max_output_tokens_per_question * n, self.cfg.generation.max_output_tokens_per_call)
        return gate.call("routine", self._adapter("routine"), system, json.dumps(user, sort_keys=True), c.GenerationOutput.model_json_schema(), max_out)

    def _diagnose(self, gate, bundle, repo, latest, rejected, diagnostics) -> dict | None:
        version, system = load_prompt("diagnose")
        user = {"question": bundle["question"], "context_values": bundle["context_values"],
                "available": {"templates": [{"id": t["id"], "body": t["body"]} for t in bundle["templates"]], "evidence": bundle["evidence"]},
                "rejected_candidates": [{"id": cid, "body": (repo.candidate(cid) or {}).get("body"), **rejected.get(cid, {})} for cid in latest]}
        r = gate.call("advanced", self._adapter("advanced"), system, json.dumps(user, sort_keys=True),
                      c.DiagnosisOutput.model_json_schema(), self.cfg.generation.max_output_tokens_per_question)
        if r.status != "ok":
            diagnostics.append(f"diagnosis {r.status}: {r.error or ''}; proceeding without it")
            return None
        try:
            return c.DiagnosisOutput.model_validate(r.data).model_dump()
        except Exception as exc:
            diagnostics.append(f"diagnosis schema-invalid: {exc}"[:200])
            return None

    def _targeted_batches(self, repo, session_id, qid) -> list[list[str]]:
        rows = repo.conn.execute(
            "SELECT batch_id, id FROM candidate WHERE scope_id=? AND session_id=? AND question_id=? AND variant='alternative' "
            "AND status='valid' ORDER BY created_at, id",
            (repo.scope, session_id, qid)).fetchall()
        batches: dict[str, list[str]] = {}
        for b, cid in rows:
            batches.setdefault(b, []).append(cid)
        return list(batches.values())

    def _rejections(self, repo, session_id, qid, payload_rejected) -> dict[str, dict]:
        out = {}
        for r in repo.conn.execute(
            "SELECT f.candidate_id, f.reasons_json, f.free_text FROM feedback f JOIN candidate c ON c.id=f.candidate_id "
            "WHERE f.outcome='rejected' AND c.scope_id=? AND c.session_id=? AND c.question_id=?", (repo.scope, session_id, qid)):
            out[r[0]] = {"reasons": json.loads(r[1]), "free_text": r[2]}
        for r in payload_rejected:
            out[r["candidate_id"]] = {"reasons": r["reasons"], "free_text": r["free_text"]}
        return out

    def _shown(self, repo, session_id, qid) -> list[str]:
        return [r[0] for r in repo.conn.execute(
            "SELECT DISTINCT e.candidate_id FROM exposure e JOIN candidate c ON c.id=e.candidate_id "
            "WHERE c.scope_id=? AND c.session_id=? AND c.question_id=?", (repo.scope, session_id, qid))]

    # -- node 3: evaluate (deterministic; the semantic evaluator is the diagnosis step above) --------
    def evaluate(self, s: AgentState) -> dict:
        ev, repo = s["event"], self._repo(s["event"]["scope_id"])
        questions = {q["id"]: q for q in s["session"]["state"]["questions"]}
        allowed = {v["id"] for v in repo.variables()}
        diagnostics = list(s["diagnostics"])
        for cd in repo.candidates(ev["session_id"], statuses=("unevaluated",)):
            bundle = s["bundles"].get(cd["question_id"], {})
            known_refs = {t["id"] for t in bundle.get("templates", [])} | {e["id"] for e in bundle.get("evidence", [])}
            problems = []
            if bad := unauthorized_variables(cd["body"], allowed):
                problems.append(f"unauthorized variables {bad}")
            refs = cd["evidence_refs"] + cd["template_refs"]
            if not refs:
                problems.append("no evidence or template reference")
            elif unknown := [r for r in refs if r not in known_refs]:
                problems.append(f"references outside the bundle {unknown}")
            if not problems:
                try:
                    rendered = render(cd["body"], self.rt.bindings)
                    problems += check_constraints(rendered, c.Constraints(**questions[cd["question_id"]]["constraints"]))
                except KeyError as exc:
                    problems.append(f"no binding for {exc}")
            status = "invalid" if problems else "valid"
            repo.set_candidate_status(cd["id"], status, {**cd["validation"], "problems": problems, "checked_at": _now()})
            if problems:
                diagnostics.append(f"{cd['question_id']} candidate {cd['id'][:8]} invalid: {'; '.join(problems)}")
        return {"diagnostics": diagnostics}

    # -- node 4: persist / learn ----------------------------------------------------------------------
    def persist(self, s: AgentState) -> dict:
        ev, payload, repo = s["event"], s["payload"], self._repo(s["event"]["scope_id"])
        session = s["session"] or repo.session(ev["session_id"]) or {"revision": None, "state": {"values": {}}}
        diagnostics, unresolved = list(s["diagnostics"]), list(s["unresolved"])
        flat = {v for vals in session["state"].get("values", {}).values() for v in vals}
        status = s.get("status")
        cands: list[dict] = []
        cached: dict[str, list[str]] = {}

        if ev["type"] == "record_feedback":
            o = payload["outcome"]
            if o == "shown":
                repo.record_exposure(ev["event_id"], payload["shown"], payload["alternatives"], {"values": sorted(flat)})
            elif payload["candidate_id"] is None:
                diagnostics.append(f"{o} requires candidate_id")
            else:
                repo.record_feedback(ev["event_id"], payload["candidate_id"], o, payload["reasons"], payload["free_text"] or payload["edited_body"], flat, self.cfg.ranking)
                if o == "approved":
                    if payload["approve_as_template_id"]:
                        repo.promote_candidate(payload["candidate_id"], payload["approve_as_template_id"], "user", _now())
                    else:
                        diagnostics.append("approved without approve_as_template_id: preference recorded, wording not promoted")
            status = status or "ready"
        elif ev["type"] == "get_candidate":
            found = repo.candidates(ev["session_id"], payload["question_id"])
            if payload["candidate_id"]:
                found = [x for x in found if x["id"] == payload["candidate_id"]]
            if payload["variant"]:
                found = [x for x in found if x["variant"] == payload["variant"]]
            cands = found
            if not found:
                diagnostics.append("cache miss; no generation authorized by get_candidate")
                status = status or "partial"
        elif ev["type"] in GENERATING and status is None:
            for qid in s["targets"]:
                valid = repo.candidates(ev["session_id"], qid)
                if qid in s["immediate"] and ev["type"] == "regenerate_question":
                    cands += [x for x in valid if x["batch_id"] == ev["event_id"]]
                    cached[qid] = [x["id"] for x in valid if x["batch_id"] != ev["event_id"]]
                elif qid in s["immediate"]:
                    cands += valid
                elif valid:
                    cached[qid] = [x["id"] for x in valid]
            immediate_ok = {x["question_id"] for x in cands}
            missing = [q for q in s["immediate"] if q not in immediate_ok]
            reasons = {u["reason"] for u in unresolved}
            if "budget_exhausted" in reasons and missing:
                status = "budget_exhausted"
            elif not cands and missing:
                status = "needs_information" if reasons and reasons <= {"insufficient_evidence", "hidden_value_reasoning", "conflicting_evidence", "out_of_scope"} else "failed"
            elif missing or unresolved:
                status = "partial"
            else:
                status = "ready"
        status = status or "ready"

        result = c.Result(
            event_id=ev["event_id"], status=status, revision=session["revision"],
            candidates=[self._out(x) for x in cands], cached=cached,
            evidence_refs=sorted({r for x in cands for r in x["evidence_refs"]}),
            unresolved=[c.Unresolved(**u) for u in unresolved],
            usage=c.Usage(**repo.session_usage(ev["session_id"])),
            next_action={"needs_feedback": "collect structured rejection reasons, then regenerate_question",
                         "needs_information": "add evidence/templates or answer manually",
                         "budget_exhausted": "raise limits or stop"}.get(status),
            diagnostics=diagnostics + ([f"diagnosis: {s['diagnosis']['diagnosis']}"] if s.get("diagnosis") else []),
        )
        return {"result": self._finish(repo, ev, result), "status": status}

    @staticmethod
    def _out(x: dict) -> c.CandidateOut:
        return c.CandidateOut(id=x["id"], question_id=x["question_id"], variant=x["variant"], body=x["body"], variables=x["variables"],
                              evidence_refs=x["evidence_refs"], template_refs=x["template_refs"], status=x["status"],
                              form_revision=x["form_revision"], validation={k: v for k, v in x["validation"].items() if k != "ranking"},
                              self_report=x["self_report"], ranking=x["validation"].get("ranking"))

    @staticmethod
    def _finish(repo: Repository, ev: dict, result: c.Result) -> dict:
        d = result.model_dump()
        repo.record_event(ev["event_id"], ev["session_id"], ev["type"], d)
        return d


def handle_event(event: dict, runtime: RuntimeDeps) -> dict:
    """Convenience for one-shot use; hosts should keep one Agent per process instead."""
    return Agent(runtime).handle_event(event)
