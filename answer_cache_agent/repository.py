"""Scope-bound data access: metamodel, evidence, templates, sessions, candidates, feedback, events, ledger."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from answer_cache_agent.config import RankingConfig
from answer_cache_agent.embeddings import Embedder
from answer_cache_agent.ranking import Stats, apply_outcome, backoff_keys
from answer_cache_agent.vectors import VectorStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """Every query is bound to one scope_id; cross-scope access is impossible through this class."""

    def __init__(self, conn: sqlite3.Connection, scope_id: str, embedder: Embedder, store: VectorStore) -> None:
        self.conn, self.scope, self.embedder, self.store = conn, scope_id, embedder, store

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    # -- metamodel -------------------------------------------------------------
    def add_dimension(self, id: str, label: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO dimension VALUES (?,?,?)", (id, self.scope, label))

    def add_value(self, id: str, dimension_id: str, label: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO value_ VALUES (?,?,?,?)", (id, self.scope, dimension_id, label))

    def assign(self, subject_type: str, subject_id: str, value_id: str, mode: str = "applies", source: str = "caller") -> None:
        self.conn.execute("INSERT OR REPLACE INTO assignment VALUES (?,?,?,?,?,?)",
                          (self.scope, subject_type, subject_id, value_id, mode, source))

    def clear_assignments(self, subject_type: str, subject_id: str) -> None:
        self.conn.execute("DELETE FROM assignment WHERE scope_id=? AND subject_type=? AND subject_id=?",
                          (self.scope, subject_type, subject_id))

    def assignments(self, subject_type: str, subject_id: str) -> dict[str, dict[str, set[str]]]:
        """Returns {'applies': {dimension: {values}}, 'requires': {...}}."""
        rows = self.conn.execute(
            "SELECT a.mode, v.dimension_id, a.value_id FROM assignment a JOIN value_ v ON v.scope_id=a.scope_id AND v.id=a.value_id "
            "WHERE a.scope_id=? AND a.subject_type=? AND a.subject_id=?", (self.scope, subject_type, subject_id)).fetchall()
        out: dict[str, dict[str, set[str]]] = {"applies": {}, "requires": {}}
        for mode, dim, val in rows:
            out[mode].setdefault(dim, set()).add(val)
        return out

    # -- variables (descriptors only) -------------------------------------------
    def add_variable(self, id: str, safe_description: str, value_type: str, permitted_use: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO variable VALUES (?,?,?,?,?)",
                          (id, self.scope, safe_description, value_type, permitted_use))

    def variables(self, ids: list[str] | None = None) -> list[dict]:
        q, args = "SELECT * FROM variable WHERE scope_id=?", [self.scope]
        if ids is not None:
            q += f" AND id IN ({','.join('?' * len(ids))})"
            args += ids
        return [dict(r) for r in self.conn.execute(q, args)]

    # -- evidence (lane 1) ---------------------------------------------------------
    def add_evidence(self, id: str, locator: str, version: str, excerpt: str, disclosure: str,
                     approved_by: str, approved_at: str) -> None:
        with self.transaction():
            self.conn.execute("INSERT OR REPLACE INTO evidence VALUES (?,?,?,?,?,?,?,?,NULL)",
                              (id, self.scope, locator, version, excerpt, disclosure, approved_by, approved_at))
            self._index(id, "evidence", excerpt)

    def revoke_evidence(self, id: str) -> None:
        with self.transaction():
            self.conn.execute("UPDATE evidence SET revoked_at=? WHERE scope_id=? AND id=?", (_now(), self.scope, id))
            self.store.delete(id)

    def evidence(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM evidence WHERE scope_id=? AND id IN ({','.join('?' * len(ids))})", [self.scope, *ids])]

    # -- templates (lane 3) --------------------------------------------------------
    def add_intent_alias(self, intent: str, text: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO intent_alias VALUES (?,?,?)", (self.scope, intent, text))

    def add_template(self, id: str, intent: str, body: str, variables: list[str], evidence_ids: list[str],
                     disclosure: str, approved_by: str, approved_at: str, origin_candidate_id: str | None = None) -> None:
        with self.transaction():
            prev = self.conn.execute("SELECT version, body, intent FROM template WHERE scope_id=? AND id=?", (self.scope, id)).fetchone()
            # Version is the optimistic-concurrency token for editors, so a rename counts as a change too.
            version = prev[0] + 1 if prev and (prev[1], prev[2]) != (body, intent) else (prev[0] if prev else 1)
            self.conn.execute(
                "INSERT OR REPLACE INTO template VALUES (?,?,?,?,?,'approved',?,?,?,NULL,?)",
                (id, self.scope, intent, body, version, disclosure, approved_by, approved_at, origin_candidate_id))
            self.conn.execute("DELETE FROM template_variable WHERE scope_id=? AND template_id=?", (self.scope, id))
            self.conn.execute("DELETE FROM template_evidence WHERE scope_id=? AND template_id=?", (self.scope, id))
            self.conn.executemany("INSERT INTO template_variable VALUES (?,?,?)", [(self.scope, id, v) for v in variables])
            self.conn.executemany("INSERT INTO template_evidence VALUES (?,?,?)", [(self.scope, id, e) for e in evidence_ids])
            aliases = [r[0] for r in self.conn.execute(
                "SELECT text FROM intent_alias WHERE scope_id=? AND intent=?", (self.scope, intent))]
            self._index(id, "template", "\n".join([*aliases, body]))

    def revoke_template(self, id: str) -> None:
        with self.transaction():
            self.conn.execute("UPDATE template SET status='revoked', revoked_at=? WHERE scope_id=? AND id=?",
                              (_now(), self.scope, id))
            self.store.delete(id)

    def template(self, id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM template WHERE scope_id=? AND id=?", (self.scope, id)).fetchone()
        if row is None:
            return None
        t = dict(row)
        t["variables"] = [r[0] for r in self.conn.execute(
            "SELECT variable_id FROM template_variable WHERE scope_id=? AND template_id=?", (self.scope, id))]
        t["evidence_ids"] = [r[0] for r in self.conn.execute(
            "SELECT evidence_id FROM template_evidence WHERE scope_id=? AND template_id=?", (self.scope, id))]
        t.update(self.assignments("template", id))
        return t

    def _index(self, item_id: str, kind: str, text: str) -> None:
        vec = self.embedder.embed([text])[0]
        self.store.upsert(item_id, self.scope, kind, self.embedder.model_id, vec)

    def search(self, query: str, kind: str, k: int) -> list[tuple[str, float]]:
        """Semantic neighbours within this scope: [(item_id, cosine similarity)]."""
        vec = self.embedder.embed([query])[0]
        return self.store.search(self.scope, kind, self.embedder.model_id, vec, k)

    # -- sessions ----------------------------------------------------------------
    def save_session(self, id: str, revision: str, state: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO form_session VALUES (?,?,?,?,?)",
                          (id, self.scope, revision, json.dumps(state, sort_keys=True), _now()))

    def session(self, id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM form_session WHERE id=? AND scope_id=?", (id, self.scope)).fetchone()
        return None if row is None else {"id": row["id"], "revision": row["revision"], "state": json.loads(row["state_json"])}

    # -- candidates ----------------------------------------------------------------
    def add_candidate(self, c: dict) -> None:
        """Write-through on generation; replay-safe via the primary key."""
        self.conn.execute(
            "INSERT OR IGNORE INTO candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (c["id"], self.scope, c["session_id"], c["question_id"], c["batch_id"], c["variant"], c["body"],
             json.dumps(c.get("variables", [])), json.dumps(c.get("evidence_refs", [])), json.dumps(c.get("template_refs", [])),
             c["prompt_version"], c["model_id"], c["form_revision"], c.get("status", "unevaluated"),
             json.dumps(c.get("validation", {})), json.dumps(c.get("self_report", {})), _now()))

    def set_candidate_status(self, id: str, status: str, validation: dict | None = None) -> None:
        self.conn.execute("UPDATE candidate SET status=?, validation_json=COALESCE(?, validation_json) WHERE id=? AND scope_id=?",
                          (status, None if validation is None else json.dumps(validation), id, self.scope))

    def candidates(self, session_id: str, question_id: str | None = None, statuses: tuple[str, ...] = ("valid",)) -> list[dict]:
        q = f"SELECT * FROM candidate WHERE scope_id=? AND session_id=? AND status IN ({','.join('?' * len(statuses))})"
        args: list = [self.scope, session_id, *statuses]
        if question_id is not None:
            q += " AND question_id=?"
            args.append(question_id)
        return [self._candidate(r) for r in self.conn.execute(q + " ORDER BY created_at, variant", args)]

    def candidate(self, id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM candidate WHERE id=? AND scope_id=?", (id, self.scope)).fetchone()
        return None if row is None else self._candidate(row)

    @staticmethod
    def _candidate(row: sqlite3.Row) -> dict:
        c = dict(row)
        for k in ("variables", "evidence_refs", "template_refs", "validation", "self_report"):
            c[k] = json.loads(c.pop(f"{k}_json"))
        return c

    def mark_stale(self, session_id: str, current_revision: str) -> int:
        """Invalidate candidates generated against another form revision (PRD §12)."""
        cur = self.conn.execute(
            "UPDATE candidate SET status='stale' WHERE scope_id=? AND session_id=? AND form_revision<>? AND status IN ('valid','unevaluated')",
            (self.scope, session_id, current_revision))
        return cur.rowcount

    def promote_candidate(self, candidate_id: str, template_id: str, approved_by: str, approved_at: str) -> None:
        """Lane 3 promotion: wording becomes reusable; evidence refs are carried, never created (Q8)."""
        c = self.candidate(candidate_id)
        if c is None:
            raise KeyError(candidate_id)
        self.add_template(template_id, intent=c["question_id"], body=c["body"], variables=c["variables"],
                          evidence_ids=c["evidence_refs"], disclosure="model_visible",
                          approved_by=approved_by, approved_at=approved_at, origin_candidate_id=candidate_id)
        with self.transaction():
            for r in self.conn.execute("SELECT * FROM pref_stats WHERE scope_id=? AND subject_id=?", (self.scope, candidate_id)).fetchall():
                self.conn.execute("INSERT OR REPLACE INTO pref_stats VALUES (?,?,?,?,?,?,?,?)",
                                  (self.scope, template_id, r["context_key"], r["sel"], r["rej"], r["edit"], r["shown"], r["updated_at"]))

    # -- feedback (lane 2) -----------------------------------------------------------
    def record_exposure(self, event_id: str, shown: list[str], alternatives: list[str], context: dict) -> None:
        for i, cid in enumerate(shown):
            self.conn.execute("INSERT OR IGNORE INTO exposure VALUES (?,?,?,?,?,?,?)",
                              (self.scope, event_id, cid, i, json.dumps(alternatives), json.dumps(context, sort_keys=True), _now()))

    def record_feedback(self, event_id: str, candidate_id: str, outcome: str, reasons: list[str], free_text: str | None,
                        form_values: set[str], cfg: RankingConfig) -> bool:
        """Exactly-once: returns False if this event_id was already applied. Updates stats along the back-off ladder."""
        with self.transaction():
            if self.conn.execute("SELECT 1 FROM feedback WHERE scope_id=? AND event_id=?", (self.scope, event_id)).fetchone():
                return False
            self.conn.execute("INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?)",
                              (self.scope, event_id, candidate_id, outcome, json.dumps(reasons), free_text,
                               json.dumps(sorted(form_values)), cfg.policy_version, _now()))
            if cfg.learning_enabled:
                subject = self._stats_subject(candidate_id)
                now = datetime.now(timezone.utc)
                for key in backoff_keys(form_values):
                    s = apply_outcome(self.stats(subject, key) or Stats(updated_at=now), outcome, now, cfg)
                    self.conn.execute("INSERT OR REPLACE INTO pref_stats VALUES (?,?,?,?,?,?,?,?)",
                                      (self.scope, subject, key, s.sel, s.rej, s.edit, s.shown, s.updated_at.isoformat()))
            return True

    def _stats_subject(self, candidate_id: str) -> str:
        c = self.candidate(candidate_id)
        if c and c["template_refs"]:
            return c["template_refs"][0]
        return candidate_id

    def stats(self, subject_id: str, key: str) -> Stats | None:
        r = self.conn.execute("SELECT * FROM pref_stats WHERE scope_id=? AND subject_id=? AND context_key=?",
                              (self.scope, subject_id, key)).fetchone()
        return None if r is None else Stats(r["sel"], r["rej"], r["edit"], r["shown"], datetime.fromisoformat(r["updated_at"]))

    # -- events and ledger (Q7) ---------------------------------------------------------
    def event_result(self, event_id: str) -> dict | None:
        r = self.conn.execute("SELECT result_json FROM event WHERE scope_id=? AND event_id=?", (self.scope, event_id)).fetchone()
        return None if r is None else json.loads(r[0])

    def record_event(self, event_id: str, session_id: str, type: str, result: dict) -> None:
        self.conn.execute("INSERT OR IGNORE INTO event VALUES (?,?,?,?,?,?)",
                          (self.scope, event_id, session_id, type, json.dumps(result, sort_keys=True), _now()))

    def reserve_call(self, call_id: str, event_id: str, session_id: str, role: str, model_id: str, est_in: int, est_out: int) -> None:
        now = _now()
        self.conn.execute("INSERT OR IGNORE INTO usage_ledger VALUES (?,?,?,?,?,?,'reserved',?,?,NULL,NULL,NULL,?,?)",
                          (call_id, self.scope, event_id, session_id, role, model_id, est_in, est_out, now, now))

    def confirm_call(self, call_id: str, actual_in: int, actual_out: int, cost_usd: float | None) -> None:
        self.conn.execute("UPDATE usage_ledger SET state='confirmed', actual_in=?, actual_out=?, cost_usd=?, updated_at=? WHERE call_id=?",
                          (actual_in, actual_out, cost_usd, _now(), call_id))

    def mark_uncertain(self, call_id: str) -> None:
        self.conn.execute("UPDATE usage_ledger SET state='uncertain', updated_at=? WHERE call_id=?", (_now(), call_id))

    def session_usage(self, session_id: str) -> dict:
        """Uncertain calls count at their estimate — never zero (PRD §11)."""
        r = self.conn.execute(
            "SELECT COUNT(*) AS calls,"
            " SUM(CASE WHEN state='confirmed' THEN actual_in+actual_out ELSE est_in+est_out END) AS tokens,"
            " SUM(COALESCE(cost_usd,0)) AS cost_usd,"
            " SUM(state='uncertain') AS uncertain FROM usage_ledger WHERE scope_id=? AND session_id=?", (self.scope, session_id)).fetchone()
        return {"calls": r["calls"] or 0, "tokens": r["tokens"] or 0, "cost_usd": r["cost_usd"] or 0.0, "uncertain": r["uncertain"] or 0}

    def uncertain_calls(self, event_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT call_id FROM usage_ledger WHERE scope_id=? AND event_id=? AND state='uncertain'", (self.scope, event_id))]
