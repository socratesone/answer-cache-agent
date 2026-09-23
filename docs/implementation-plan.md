# Implementation Plan

_Derived from `PRD.md` and the decided `design-review.md` (2026-09-21). Build record: this package is hand-built; see `build-record.md`._

## Package layout

```text
answer_cache_agent/
  config.py         Pydantic model + loader for config.yaml (all tunables; structural invariants stay in code)
  config.yaml       Default tunables
  contracts.py      Pydantic contracts: events, results, candidate/feedback/rejection records, statuses
  db.py             SQLite connection factory + DDL (application tables + sqlite-vec table)
  repository.py     Scoped CRUD, event dedup, usage ledger, preference stats, invalidation
  embeddings.py     Embedder protocol; HashEmbedder (tests); FastEmbedEmbedder (v1)
  vectors.py        VectorStore protocol; SqliteVecStore (v1)
  ranking.py        Deterministic filter → components → capped linear score; back-off ladder
  rendering.py      {{var}} substitution as data, authorization check, post-substitution constraints
  providers/        ProviderAdapter protocol; openai.py, anthropic.py, fake.py; usage normalization; refusal/truncation mapping
  prompts/          Versioned prompt files: initial_v1, targeted_v1, diagnose_v1
  budget.py         PaidCallGate: limit check -> ledger reserve -> leak check -> send -> confirm | uncertain
  graph.py          RuntimeDeps, Agent (four nodes as methods), router, SqliteSaver, handle_event; state = refs + bounded context
  ingest.py         JSONL import (Q10)
  harness.py        Browser-independent CLI: run an event file against a session
scripts/spike_retrieval.py   Q3 spike (real fastembed + sqlite-vec, paraphrase check)
tests/                      pytest; HashEmbedder; synthetic fixtures (one personal-application, one org questionnaire)
```

## Phases

| Phase | Deliverable | Acceptance scenarios covered (PRD §13) |
|---|---|---|
| 1 | `config`, `db`, `repository`, `embeddings`, `vectors`, `ranking`, **Q3 spike** | Paraphrased question; same question different context; duplicate feedback event (ledger/stat idempotency) |
| 2 | `contracts`, `rendering`, `providers` (with a `FakeProvider` for tests), prompts | Protected variable; unauthorized variable reference; overlong resolved answer |
| 3 (done) | `graph.py` + `budget.py`; nodes live as `Agent` methods rather than a `nodes/` package (fewer files, same four nodes) | Prepare with no paid call; initial generation; cached concise; targeted regeneration; hidden candidate; missing evidence; stale form; budget exhaustion; restart/partial failure |
| 4 (done) | `ingest`, `harness`, fixtures, `scripts/evaluate.py`, `build-record.md`, `architecture.md`, `README.md` | Evaluation report; deliverables |

## Structural invariants (code, not YAML)

- Initial variants = 2 (standard, concise); targeted regeneration ≤ 5.
- Prepare, `get_candidate`, `record_feedback`, `update_form` make zero paid calls.
- Filters (`scope`, approval, `requires`, source currency) run before any scoring; preference weight is capped by config but the cap's existence is structural.
- Generated text never enters the `evidence` table.
- Bindings and credentials travel only in `config["configurable"]`, never in graph state or checkpoints.
- Every paid call has a ledger row reserved before send; `uncertain` rows are never auto-retried.
- Semantic evaluator runs only when a targeted set is exhausted by explicit rejection.

## Event router (Phase 3 sketch)

```text
route(event):
  prepare_form / update_form  → prepare → persist
  get_candidate               → prepare(load only) → persist(result)         # no generate
  generate_initial            → prepare → generate(initial) → evaluate(deterministic) → persist
  regenerate_question         → prepare → [diagnose if set exhausted & reasons present] → generate(targeted) → evaluate → persist
  record_feedback             → persist
```

`needs_feedback` fires when a targeted set is exhausted and no structured rejection reasons were supplied; with reasons, one diagnosis + one more targeted round is allowed before `needs_feedback` becomes terminal for that question (rounds are a tunable).
