# CODEX.md — Contract for the UI / UX / Browser-Extension Agent

_You are building the surrounding application: the Chrome extension, the local host process, the settings UI, and the bridge that calls this Python agent. This file is the map. It tells you what the agent is, what is fixed, which files are the contract, and how to verify your bridge. Read it first; the linked files have the depth._

**Agent version:** 0.1 (all four build phases complete, 2026-09-22). **Tests:** 39 passing offline. **Nothing here is speculative** — every referenced file exists and is exercised by tests.

## 1. What you own vs what the agent owns

| You (extension + host + UI) | The agent (`answer_cache_agent/`) |
|---|---|
| Extract questions, constraints, sanitized page context from the page | Validate and store form context; compute the form revision |
| Deterministic autofill from the user's approved templates; report which fields are already filled | Semantic retrieval over the user's templates/evidence; context ranking |
| Hold **private variable values** and **provider API keys**; pass both to the agent as runtime dependencies, never in payloads | Keep both out of every model request, checkpoint, and log; generate templates with `{{variable_id}}` placeholders |
| Render `{{placeholders}}` locally before display; re-check field limits after rendering | Run the same post-substitution checks on its side and flag violations in `validation` |
| Report exposure, selection, rejection, edits, approval **explicitly** | Learn from what you report; infer nothing |
| Transport (native messaging / localhost HTTP / subprocess), per-session queueing, retries with the same `event_id` | Exactly-once event application, replay of stored results, crash resume from checkpoint |
| Settings UI for dimensions, values, variables, hint rules, model roles, budget | Storage, validation, and JSONL import of those records |

The agent never: submits forms, clicks, decides whether to overwrite a field, hosts a port, infers context from page text with a model, or auto-retries a paid call whose outcome it did not observe.

## 2. The contract files (build against these, in this order)

| Purpose | File | Notes |
|---|---|---|
| **Wire contract — generate your types from these** | [`schemas/*.schema.json`](schemas/) | JSON Schema 2020-12 for `Event`, the six payloads, `Result`, `CandidateOut`, `GenerationOutput`, `DiagnosisOutput`. `additionalProperties: false` everywhere. Regenerate with `python scripts/export_schemas.py` if the agent changes. |
| Source of truth for those schemas | [`answer_cache_agent/contracts.py`](answer_cache_agent/contracts.py) | Pydantic models with field descriptions; the statuses, outcomes, variants, and unresolved-reason enums are here. |
| **Integration guide — the detailed protocol** | [`docs/integration-guide.md`](docs/integration-guide.md) | Topology, trust boundary, every event with a JSON example, session/revision/event-id rules, exposure & feedback do/don't table, rendering spec, status → UI action table, ingest format, ship checklist. |
| Python entrypoint you call | [`answer_cache_agent/graph.py`](answer_cache_agent/graph.py) → `RuntimeDeps`, `Agent.handle_event(event: dict) -> dict` | One `Agent` per host process; not thread-safe; rotate keys/bindings by assigning `agent.rt.credentials` / `agent.rt.bindings`. |
| Runtime-dependency types | [`answer_cache_agent/providers/__init__.py`](answer_cache_agent/providers/__init__.py) → `Credentials`, `ModelRef`, `ModelRoles` | `ModelRef(provider="openai"\|"anthropic", model="…")`; both roles may point at the same model. |
| Placeholder rendering (reuse or re-implement) | [`answer_cache_agent/rendering.py`](answer_cache_agent/rendering.py) | Syntax is `{{identifier}}`, nothing else. `render`, `referenced_variables`, `check_constraints`, `find_leaks`. |
| CLI / subprocess alternative and the event-script format | [`answer_cache_agent/harness.py`](answer_cache_agent/harness.py) | `answer-cache-agent events.jsonl --db … --scope … --bindings … --json`; `$last` / `$cands.N.id` placeholders. |
| Knowledge import format | [`answer_cache_agent/ingest.py`](answer_cache_agent/ingest.py) + [`fixtures/*/knowledge.jsonl`](fixtures/) | Your settings UI writes these records (or calls the repository API). Variable *values* never go in. |
| **Worked examples of a full session** | [`fixtures/personal_application/events.jsonl`](fixtures/personal_application/events.jsonl), [`fixtures/org_questionnaire/events.jsonl`](fixtures/org_questionnaire/events.jsonl) | Copy these as your first bridge tests. Bindings and knowledge sit beside them. |
| Tunables the settings UI may expose | [`answer_cache_agent/config.yaml`](answer_cache_agent/config.yaml) | Validated by [`config.py`](answer_cache_agent/config.py); pass a custom file via `RuntimeDeps(config_path=…)`. Do not invent settings that are not in this file. |
| How it works inside (four nodes, privacy boundary, ranking, limitations) | [`docs/architecture.md`](docs/architecture.md) | Read §4 (privacy boundary) and §6 (known limitations) before designing UI copy. |
| Product requirements and the decisions behind them | [`docs/PRD.md`](docs/PRD.md), [`docs/design-review.md`](docs/design-review.md) | The design-review "Owner decisions" block is binding. |
| Evaluation numbers and what they do / don't claim | [`docs/evaluation-report.md`](docs/evaluation-report.md) | Regenerate with `python scripts/evaluate.py [--real]`. |
| Build provenance | [`docs/build-record.md`](docs/build-record.md) | Hand-built; Foundry composer not used. |

## 3. The protocol in one screen

```text
per form instance:   session_id = uuid (yours, stable for the tab/form)
per user action:     event_id  = uuid (fresh per attempt; RETRY WITH THE SAME ID)
every event after the first: expected_revision = previous Result.revision

1. prepare_form          -> ready                         (0 paid calls)
2. generate_initial      -> ready|partial|needs_information|budget_exhausted|failed
                            candidates = requested fields; cached = pre-generated others
3. record_feedback shown -> ready                         (send the moment candidates render)
4. get_candidate         -> ready|partial                 (0 paid calls; partial = cache miss, nothing generated)
5. record_feedback selected|edited|rejected|approved      (one event per fact; never inferred)
6. regenerate_question   -> ready|needs_feedback|…        (<=5 alternatives; needs_feedback = ask the user why)
7. update_form           -> ready, new revision           (old candidates become stale)
any: stale_context       -> re-extract, update_form, retry with the new revision
any: failed + usage.uncertain>0 -> a paid call's outcome is unknown; retry only with a NEW event_id after user OK
```

Candidate `body` is **unrendered**. Render locally, then re-check length.

## 4. Non-negotiables (the agent enforces them; your bridge must respect them)

1. **Payloads never carry keys, private values, or file paths.** Schemas reject unknown fields, but a key inside `page_context` would pass — sanitize before sending.
2. **Bindings and credentials travel only in `RuntimeDeps`.** They reach the agent process (it needs bindings for post-substitution checks) but never a model, checkpoint, session row, or log; `find_leaks` blocks any outbound payload containing a binding value.
3. **Context is deterministic.** Hints come from the page state you already have, explicit user selections, and user-defined regex rules. No model inference of context.
4. **Rejection is explicit.** "Asked for more" ≠ rejected; "left unused" ≠ rejected. Your reason codes are yours; the agent stores and forwards them opaquely (starter set in the guide §6).
5. **Approval promotes wording, not facts.** `approved` + `approve_as_template_id` makes the text a reusable template; it never becomes factual evidence.
6. **Descriptors only.** The model cannot reason about a private value's contents. When a question needs that, the agent returns `needs_information` / `hidden_value_reasoning`; the UI must offer manual answer or "expose this fact".
7. **One agent per process, one worker per session.** Construct `Agent` once (embedding model load ≈ 6 s cold); queue events per `session_id`.

## 5. Verify your bridge

```bash
pip install -e ".[dev]" && pytest -q                                  # 39 passed
answer-cache-agent --demo personal_application --db /tmp/d1.db        # prints ANSWER_CACHE_AGENT_DEMO_OK
answer-cache-agent --demo org_questionnaire --db /tmp/d2.db
```

Then, with your bridge in place, drive the same `fixtures/*/events.jsonl` through it and diff the statuses and candidate counts against the harness output (`--json` prints full results). A bridge that reproduces those two scripts — including the `partial` on the 80-character SOC 2 field after substitution and the `insufficient_evidence` abstention on the regulatory-audit question — has the protocol right.

For offline UI development, run the agent with `RuntimeDeps(adapters={"routine": demo_provider(), "advanced": demo_provider("fake-adv", diagnoser=True)}, embedder=HashEmbedder())` from `answer_cache_agent.providers.fake` / `answer_cache_agent.embeddings`; no keys, no model download, deterministic output.

## 6. Open items the agent side has not done (do not build around assumptions)

- Real OpenAI/Anthropic adapters are wired and constructed under test but have not been exercised against live APIs. First live run belongs to whoever has keys; report normalization issues as issues against `providers/openai.py` / `providers/anthropic.py`.
- No HTTP server, no native-messaging host, no packaging/installer — all yours (FDR: the agent is a library).
- Encryption at rest of the SQLite file is not provided; you own the private store's protection.
- Per-question variable authorization is scope-wide in v1.

If any of this conflicts with what your UI needs, change the contract by editing `contracts.py` + re-exporting schemas in a PR — never by sending fields the schema does not declare.
