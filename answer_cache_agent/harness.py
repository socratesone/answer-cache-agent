"""Browser-independent harness: replay an event script against a database, offline (--fake) or with real providers."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from answer_cache_agent.config import load_config
from answer_cache_agent.db import connect, init_schema
from answer_cache_agent.embeddings import FastEmbedEmbedder, HashEmbedder
from answer_cache_agent.graph import Agent, RuntimeDeps
from answer_cache_agent.providers import Credentials, ModelRef, ModelRoles
from answer_cache_agent.providers.fake import demo_provider
from answer_cache_agent.repository import Repository
from answer_cache_agent.vectors import SqliteVecStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SUCCESS_MARKER = "ANSWER_CACHE_AGENT_DEMO_OK"


def make_embedder(hash_embedder: bool, config_path: str | None = None):
    return HashEmbedder() if hash_embedder else FastEmbedEmbedder(load_config(config_path).retrieval.embedding_model)


def open_repository(db: str, scope: str, hash_embedder: bool) -> Repository:
    emb = make_embedder(hash_embedder)
    conn = connect(db)
    init_schema(conn, emb.model_id, emb.dim)
    return Repository(conn, scope, emb, SqliteVecStore(conn))


def parse_model(spec: str) -> ModelRef:
    provider, _, model = spec.partition(":")
    return ModelRef(provider, model)  # type: ignore[arg-type]


def build_agent(db: str, fake: bool, hash_embedder: bool, bindings: dict, routine: str | None, advanced: str | None,
                config_path: str | None = None) -> Agent:
    adapters = {"routine": demo_provider(), "advanced": demo_provider("fake-adv", diagnoser=True)} if fake else None
    roles = None if fake else ModelRoles(parse_model(routine or "openai:gpt-4o-mini"), parse_model(advanced or routine or "openai:gpt-4o-mini"))
    # Credentials come from the process environment: a trusted runtime interface, never an event payload.
    creds = Credentials(openai_api_key=os.environ.get("OPENAI_API_KEY"), anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return Agent(RuntimeDeps(db_path=db, credentials=creds, model_roles=roles, bindings=bindings, config_path=config_path,
                             embedder=make_embedder(hash_embedder, config_path), adapters=adapters))


def _resolve(value, cands: list, last_rev: str | None):
    """`$last` -> previous revision; `$cands.0.id` -> a path into the most recent non-empty candidates list."""
    if isinstance(value, str) and value == "$last":
        return last_rev
    if isinstance(value, str) and value.startswith("$cands."):
        cur = cands
        for part in value[7:].split("."):
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        return cur
    if isinstance(value, list):
        return [_resolve(v, cands, last_rev) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, cands, last_rev) for k, v in value.items()}
    return value


def run_script(agent: Agent, events: list[dict], scope: str, session: str, out=sys.stdout) -> list[dict]:
    """Chain events: `$last`/`$cands` placeholders resolve against earlier results; missing event_ids are minted."""
    results, last_rev, cands = [], None, []
    for e in events:
        e = _resolve({"event_id": str(uuid.uuid4()), "session_id": session, "scope_id": scope, **e}, cands, last_rev)
        r = agent.handle_event(e)
        cands = r["candidates"] or cands
        last_rev = r.get("revision") or last_rev
        results.append(r)
        if out:
            print(json.dumps({"event": e["type"], "status": r["status"], "candidates": [c["id"][:8] for c in r["candidates"]],
                              "cached": {k: len(v) for k, v in r["cached"].items()}, "unresolved": r["unresolved"], "usage": r["usage"]}), file=out)
    return results


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="answer-cache-agent", description="Run questionnaire-agent events without a browser.")
    p.add_argument("events", nargs="?", help="JSONL of events (see fixtures/*/events.jsonl); omit with --demo")
    p.add_argument("--db", default="answer_cache.db")
    p.add_argument("--scope", default="default")
    p.add_argument("--session", default=None)
    p.add_argument("--ingest", help="knowledge JSONL to import before running")
    p.add_argument("--bindings", help="JSON file of private variable bindings (never sent to a model)")
    p.add_argument("--fake", action="store_true", help="scripted provider; no network, no keys")
    p.add_argument("--hash-embedder", action="store_true", help="offline lexical embedder (demo/tests)")
    p.add_argument("--routine", help="provider:model for the routine role, e.g. openai:gpt-4o-mini")
    p.add_argument("--advanced", help="provider:model for the advanced role")
    p.add_argument("--demo", choices=["personal_application", "org_questionnaire"], help="run a bundled fixture end to end offline")
    p.add_argument("--json", action="store_true", help="print full results as JSON instead of the summary lines")
    a = p.parse_args(argv)

    if a.demo:
        d = FIXTURES / a.demo
        a.events, a.ingest, a.bindings = str(d / "events.jsonl"), str(d / "knowledge.jsonl"), str(d / "bindings.json")
        a.fake = a.hash_embedder = True
        a.scope = a.demo
    if not a.events:
        p.error("events file or --demo required")
    bindings = json.load(open(a.bindings, encoding="utf-8")) if a.bindings else {}
    agent = build_agent(a.db, a.fake, a.hash_embedder, bindings, a.routine, a.advanced)
    if a.ingest:
        from answer_cache_agent.ingest import ingest
        with open(a.ingest, encoding="utf-8") as fh:
            counts = ingest(agent._repo(a.scope), fh)
        print(f"ingested {dict(counts)}", file=sys.stderr)
    events = [json.loads(l) for l in open(a.events, encoding="utf-8") if l.strip()]
    results = run_script(agent, events, a.scope, a.session or str(uuid.uuid4()), out=None if a.json else sys.stdout)
    if a.json:
        print(json.dumps(results, indent=2))
    if a.demo:
        ok = results[0]["status"] == "ready" and any(r["candidates"] for r in results) and all(r["status"] != "failed" for r in results)
        print(SUCCESS_MARKER if ok else "DEMO_FAILED")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
