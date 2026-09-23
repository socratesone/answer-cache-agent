"""Q3 spike: real fastembed + sqlite-vec, paraphrase retrieval, scope filter, delete/update, latency."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from answer_cache_agent.db import connect, init_schema
from answer_cache_agent.embeddings import FastEmbedEmbedder
from answer_cache_agent.repository import Repository
from answer_cache_agent.vectors import SqliteVecStore

APPROVED = dict(disclosure="model_visible", approved_by="user", approved_at="2026-09-01")

t0 = time.perf_counter()
emb = FastEmbedEmbedder()
print(f"model {emb.model_id} dim={emb.dim} load={time.perf_counter() - t0:.1f}s")

with tempfile.TemporaryDirectory() as d:
    conn = connect(Path(d) / "spike.db")
    init_schema(conn, emb.model_id, emb.dim)
    repo = Repository(conn, "s1", emb, SqliteVecStore(conn))
    repo.add_intent_alias("motivation", "Why do you want to work here?")
    repo.add_intent_alias("relocate", "Are you willing to relocate?")
    repo.add_intent_alias("salary", "What are your salary expectations?")
    repo.add_intent_alias("strengths", "What is your greatest strength?")
    t0 = time.perf_counter()
    repo.add_template("B", "motivation", "{{v17}} I'm drawn to teams that ship evaluation tooling alongside agents.", ["v17"], [], **APPROVED)
    repo.add_template("R", "relocate", "Yes, open to relocation within the region.", [], [], **APPROVED)
    repo.add_template("S", "salary", "Negotiable based on scope and level.", [], [], **APPROVED)
    repo.add_template("G", "strengths", "Turning ambiguous requirements into shippable systems.", [], [], **APPROVED)
    print(f"indexed 4 templates in {time.perf_counter() - t0:.2f}s")

    queries = {
        "Why are you interested in this position?": "B",
        "What motivates you to apply to our company?": "B",
        "Would you consider moving for the role?": "R",
        "Compensation requirements": "S",
        "Tell us about your strongest skill": "G",
    }
    ok = True
    for q, expect in queries.items():
        t0 = time.perf_counter()
        hits = repo.search(q, "template", 4)
        ms = (time.perf_counter() - t0) * 1000
        top = hits[0][0]
        ok &= top == expect
        print(f"{'OK ' if top == expect else 'BAD'} {ms:5.1f}ms {q!r} -> {[(h, round(s, 3)) for h, s in hits]}")

    other = Repository(conn, "s2", emb, SqliteVecStore(conn))
    assert other.search("Why do you want to work here?", "template", 4) == [], "scope leak"
    repo.revoke_template("B")
    assert "B" not in [h for h, _ in repo.search("Why do you want to work here?", "template", 4)], "delete failed"
    repo.add_template("B", "motivation", "{{v17}} Updated body.", ["v17"], [], **APPROVED)
    assert repo.template("B")["version"] == 2
    print("scope isolation, delete, and re-add/version bump OK")
    print("SPIKE", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
