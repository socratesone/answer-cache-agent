# Architecture

_The four nodes, the event pathways, the privacy boundary, the ranking policy, and the known limitations (PRD §13 documentation deliverable)._

## 1. Shape

```text
                         Event (JSON)                                  Result (JSON)
                              │                                             ▲
                              ▼                                             │
   Agent.handle_event ── dedup (event_id) ── revision check ── LangGraph ───┘
                                                                 │
             ┌───────────────────────────────────────────────────┤
             │  record_feedback ─────────────────────────────▶ Persist/Learn
             │  prepare_form / update_form / get_candidate ──▶ Prepare ──▶ Persist/Learn
             │  generate_initial / regenerate_question ──────▶ Prepare ──▶ Generate ──▶ Evaluate ──▶ Persist/Learn
             └───────────────────────────────────────────────────┘
                                           │
             SQLite (one file): app tables ─┴─ sqlite-vec index ─── LangGraph checkpoints
```

One `Agent` per host process holds the database connection, the embedder, the compiled graph, and the trusted runtime inputs (credentials, model roles, private bindings). Graph **state** is a `TypedDict` of the event, the loaded session, target question ids, per-question context bundles (record references, scores, descriptors), unresolved gaps, and the result. Bindings, credentials, and adapters are never in state, so they are never in a checkpoint.

## 2. The four nodes

| Node | Paid calls | Reads | Writes | Decides |
|---|---|---|---|---|
| **Prepare / Retrieve** (`Agent.prepare`, `_bundle`) | none | session, metamodel, templates, evidence, variables, preference stats | `form_session`; marks old-revision candidates `stale` | form revision (hash of the validated payload); deterministic hints from caller/user/rules; which questions are targets (prefilled skipped unless targeted); per-question bundle: `requires`-filtered templates ranked by policy, disclosure-approved evidence, variable descriptors; `insufficient_evidence` gap when retrieval returns nothing above the floor |
| **Generate** (`Agent.generate`, `_generate_one`, `_diagnose`) | routine role, one per question; advanced role once for diagnosis | bundles, previously shown candidates, stored + supplied rejections | `candidate` rows the moment each response parses (`unevaluated`); `usage_ledger` | prompt mode; whether a targeted set is exhausted; `needs_feedback` vs diagnosis vs generation; cap of 2 initial / 5 targeted; cache reuse (skips questions that already have valid candidates) |
| **Evaluate** (`Agent.evaluate`) | none | unevaluated candidates, bundles, bindings | `candidate.status` + `validation.problems` | variable authorization, evidence/template linkage to the bundle, post-substitution length/word constraints, missing bindings → `valid` / `invalid` |
| **Persist / Learn** (`Agent.persist`) | none | valid candidates, ledger | `exposure`, `feedback`, `pref_stats`, `template` (promotion), `event` | result status; which candidates are returned vs listed as cached; ranking updates along the back-off ladder (exactly once per `event_id`) |

The **semantic evaluator** is the diagnosis call inside Generate: it runs only after every candidate of the latest targeted batch has been explicitly rejected *with* structured reasons, and its output is fed to the next targeted generation, not used as a gate. That is the owner's Q5 decision.

## 3. Event pathways and statuses

| Event | Path | Paid? | Statuses |
|---|---|---|---|
| `prepare_form` / `update_form` | prepare → persist | no | `ready` |
| `get_candidate` | prepare (load) → persist | no | `ready`, `partial` (cache miss; nothing is generated) |
| `generate_initial` | prepare → generate → evaluate → persist | per uncached question | `ready`, `partial`, `needs_information`, `budget_exhausted`, `failed` |
| `regenerate_question` | prepare → generate → evaluate → persist | 1 (+1 diagnosis) | `ready`, `needs_feedback`, `needs_information`, `budget_exhausted`, `failed` |
| `record_feedback` | persist | no | `ready` |
| any | rejected before the graph | no | `stale_context` (revision mismatch), replayed result (duplicate `event_id`) |

Durability: candidates and ledger rows are written through inside nodes; the LangGraph `SqliteSaver` checkpoint (thread = session) lets a crashed event resume at the failed node when re-sent with the same `event_id`; a call whose outcome was not observed is `uncertain`, counted at estimate, and never re-sent automatically.

## 4. Privacy boundary

```text
 model-visible                          │  local only
 ───────────────────────────────────────┼───────────────────────────────────────
 question text, constraints             │  private variable bindings ({{v17}} values)
 sanitized page_url/title/page_context  │  provider credentials
 hint values (user-defined labels)      │  database path
 template bodies (disclosure=model_visible)
 evidence excerpts (disclosure=model_visible)
 variable descriptors (id, safe_description, type, permitted_use)
 previously shown candidate bodies, rejection reasons, free text
```

Enforced by: `contracts.Event` (`additionalProperties: false`), `RuntimeDeps` as the only path for local-only data, `rendering.find_leaks` run on every outbound payload by `PaidCallGate` (a hit blocks the call), descriptor-only variables (no derived facts — Q6), `disclosure` filters in `_bundle`, and a test that asserts binding values are absent from session rows and checkpoint blobs. Prompts instruct the model to treat bundle text as data; that is defense in depth, not the boundary.

## 5. Ranking policy (v1)

Deterministic, no model call, every component recorded on the candidate (`validation.ranking`) and returned in `CandidateOut.ranking`.

1. **Filters** (before any score): same scope; `status = approved`; `disclosure = model_visible`; every `requires` value present in the form's context; similarity ≥ `retrieval.min_similarity`.
2. **Components**
   - `semantic`: cosine similarity from the vector index, min-max normalized across the retrieved set (raw value kept as `semantic_raw`).
   - `context`: `0.5 + 0.5·(hits − misses)/|known dimensions|` over the template's `applies ∪ requires` values; unknown dimensions are excluded from the denominator; a template silent on a known dimension is neutral.
   - `quality`: last evaluation score; 0.5 until an evaluator has scored the template (v1 never does, so 0.5).
   - `preference`: Beta posterior mean `(sel + edit_weight·edit + α)/(n + α + β)` at the first back-off key with `n ≥ min_n` — joint context key → single-value keys → global. The global key is consulted **only** when the form has no context at all; a known-but-sparse context gets the prior.
3. **Score** = `0.40·semantic + 0.25·context + 0.20·quality + 0.15·preference` (weights in `config.yaml`; `learning_enabled: false` zeroes the preference weight without touching recorded events).
4. **Updates** (Persist, once per `event_id`): counts decay with a 90-day half-life, then `selected` +1 sel, `rejected` +1 rej, `edited` +1 edit, `shown` +1 shown, at every key on the ladder.

Consequences the evaluation report demonstrates: a repeatedly selected same-intent runner-up overtakes its sibling in that context; the same events change nothing with learning off; an unrelated context's order is identical with learning on and off.

## 6. Known limitations

- **Initial-batch factual support is not independently checked.** Only evidence linkage (every candidate must cite bundle items) and the generator's self-report guard it; the semantic evaluator runs only after a rejected targeted set (Q5).
- **Hidden-value questions are detected by the generator**, not deterministically: it must return a `hidden_value_reasoning` abstention (Q6, descriptors only).
- **Abstention by retrieval depends on the embedder.** Under the real model, unrelated questions still score ~0.5–0.6 cosine, so `min_similarity` rarely triggers; abstention then relies on the generator.
- **`quality` is a constant 0.5 in v1** because no evaluator scores templates; the component exists so a later evaluator can populate it without a schema change.
- **Per-question authorization of variables is scope-level.** All variables in the scope are permitted for every question; per-question narrowing is a hook, not a feature.
- **Retry is the caller's job.** Adapters run with `max_retries=0`; an `uncertain` call yields `failed`, and the app retries with a new `event_id` after an explicit user OK.
- **Encryption at rest is not provided.** The SQLite file inherits OS permissions; the surrounding app owns the private store and any encryption.
- **Single-threaded `Agent`.** Concurrency across sessions is left to the host; SQLite serializes writers.
- **Real providers:** first live run (OpenAI `gpt-4o-mini`, both roles) on 2026-09-23 against `fixtures/personal_application`: 10 events, 5 paid calls, all confirmed with usage and cost, no uncertain calls (see `build-record.md`). Anthropic has not been exercised live.
