"""SQLite connection and schema. One file holds application data and the vector index."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from answer_cache_agent.vectors import SqliteVecStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Q1 metamodel: flat dimensions/values; assignments carry applies|requires.
CREATE TABLE IF NOT EXISTS dimension (
  id TEXT NOT NULL, scope_id TEXT NOT NULL, label TEXT NOT NULL,
  PRIMARY KEY (scope_id, id));
CREATE TABLE IF NOT EXISTS value_ (
  id TEXT NOT NULL, scope_id TEXT NOT NULL, dimension_id TEXT NOT NULL, label TEXT NOT NULL,
  PRIMARY KEY (scope_id, id),
  FOREIGN KEY (scope_id, dimension_id) REFERENCES dimension(scope_id, id));
CREATE TABLE IF NOT EXISTS assignment (
  scope_id TEXT NOT NULL,
  subject_type TEXT NOT NULL CHECK (subject_type IN ('form','question','template')),
  subject_id TEXT NOT NULL,
  value_id TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('applies','requires')),
  source TEXT NOT NULL CHECK (source IN ('caller','rule','user')),
  PRIMARY KEY (scope_id, subject_type, subject_id, value_id),
  FOREIGN KEY (scope_id, value_id) REFERENCES value_(scope_id, id));

-- Q6: descriptors only; bindings never enter this database.
CREATE TABLE IF NOT EXISTS variable (
  id TEXT NOT NULL, scope_id TEXT NOT NULL, safe_description TEXT NOT NULL,
  value_type TEXT NOT NULL, permitted_use TEXT NOT NULL,
  PRIMARY KEY (scope_id, id));

-- Q8 lane 1: source/factual evidence. Generated text never lands here.
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT NOT NULL, scope_id TEXT NOT NULL, locator TEXT NOT NULL, version TEXT NOT NULL,
  excerpt TEXT NOT NULL, disclosure TEXT NOT NULL CHECK (disclosure IN ('model_visible','local_only')),
  approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, revoked_at TEXT NULL,
  PRIMARY KEY (scope_id, id));

-- Q8 lane 3: approved reusable wording. origin_candidate_id preserves generated provenance.
CREATE TABLE IF NOT EXISTS template (
  id TEXT NOT NULL, scope_id TEXT NOT NULL, intent TEXT NOT NULL, body TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL CHECK (status IN ('approved','revoked')),
  disclosure TEXT NOT NULL CHECK (disclosure IN ('model_visible','local_only')),
  approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, revoked_at TEXT NULL,
  origin_candidate_id TEXT NULL,
  PRIMARY KEY (scope_id, id));
CREATE TABLE IF NOT EXISTS template_variable (
  scope_id TEXT NOT NULL, template_id TEXT NOT NULL, variable_id TEXT NOT NULL,
  PRIMARY KEY (scope_id, template_id, variable_id));
CREATE TABLE IF NOT EXISTS template_evidence (
  scope_id TEXT NOT NULL, template_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
  PRIMARY KEY (scope_id, template_id, evidence_id));
CREATE TABLE IF NOT EXISTS intent_alias (
  scope_id TEXT NOT NULL, intent TEXT NOT NULL, text TEXT NOT NULL,
  PRIMARY KEY (scope_id, intent, text));

-- Session state: bounded working context + refs (PRD §6). Bindings/credentials never here.
CREATE TABLE IF NOT EXISTS form_session (
  id TEXT NOT NULL, scope_id TEXT NOT NULL, revision TEXT NOT NULL,
  state_json TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (scope_id, id));

CREATE TABLE IF NOT EXISTS candidate (
  id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, session_id TEXT NOT NULL, question_id TEXT NOT NULL,
  batch_id TEXT NOT NULL, variant TEXT NOT NULL, body TEXT NOT NULL,
  variables_json TEXT NOT NULL, evidence_refs_json TEXT NOT NULL, template_refs_json TEXT NOT NULL,
  prompt_version TEXT NOT NULL, model_id TEXT NOT NULL, form_revision TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('unevaluated','valid','invalid','stale','needs_information')),
  validation_json TEXT NOT NULL DEFAULT '{}', self_report_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS candidate_session_q ON candidate(session_id, question_id);

-- Q8 lane 2: feedback/preference evidence.
CREATE TABLE IF NOT EXISTS exposure (
  scope_id TEXT NOT NULL, event_id TEXT NOT NULL, candidate_id TEXT NOT NULL, display_order INTEGER NOT NULL,
  alternatives_json TEXT NOT NULL, context_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (scope_id, event_id, candidate_id));
CREATE TABLE IF NOT EXISTS feedback (
  scope_id TEXT NOT NULL, event_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('selected','rejected','edited','approved')),
  reasons_json TEXT NOT NULL, free_text TEXT NULL, context_json TEXT NOT NULL,
  policy_version TEXT NOT NULL, applied_at TEXT NOT NULL,
  PRIMARY KEY (scope_id, event_id));
CREATE TABLE IF NOT EXISTS pref_stats (
  scope_id TEXT NOT NULL, subject_id TEXT NOT NULL, context_key TEXT NOT NULL,
  sel REAL NOT NULL DEFAULT 0, rej REAL NOT NULL DEFAULT 0, edit REAL NOT NULL DEFAULT 0,
  shown REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
  PRIMARY KEY (scope_id, subject_id, context_key));

-- Q7: exactly-once events and the paid-call ledger. Event/session ids are client-chosen, so they
-- are only unique within a scope.
CREATE TABLE IF NOT EXISTS event (
  scope_id TEXT NOT NULL, event_id TEXT NOT NULL, session_id TEXT NOT NULL, type TEXT NOT NULL,
  result_json TEXT NOT NULL, applied_at TEXT NOT NULL,
  PRIMARY KEY (scope_id, event_id));
CREATE TABLE IF NOT EXISTS usage_ledger (
  call_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, event_id TEXT NOT NULL, session_id TEXT NOT NULL,
  role TEXT NOT NULL, model_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('reserved','confirmed','uncertain')),
  est_in INTEGER NOT NULL, est_out INTEGER NOT NULL,
  actual_in INTEGER NULL, actual_out INTEGER NULL, cost_usd REAL NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database with the vec extension loaded and foreign keys on."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


SCHEMA_VERSION = "2"  # 2: events, sessions, feedback, exposure and ledger keyed by scope_id


def init_schema(conn: sqlite3.Connection, embedding_model: str, dim: int) -> None:
    """Create tables; refuse to mix embedding spaces (index maintenance rule, PRD §7) or schema versions."""
    conn.executescript(SCHEMA)
    SqliteVecStore.create_table(conn, dim)
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    stamp = f"{embedding_model}:{dim}"
    if "embedding" not in meta:
        conn.execute("INSERT INTO meta(key, value) VALUES ('embedding', ?), ('schema', ?)", (stamp, SCHEMA_VERSION))
    elif meta["embedding"] != stamp:
        raise RuntimeError(f"index built with {meta['embedding']}, configured {stamp}: reindex required")
    elif meta.get("schema") != SCHEMA_VERSION:
        # ponytail: no in-place migration; v0.1 databases are rebuilt from JSONL, not upgraded.
        raise RuntimeError(f"database schema {meta.get('schema', '1')} != {SCHEMA_VERSION}: recreate the database")
