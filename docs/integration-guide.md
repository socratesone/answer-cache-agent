# Integration Guide — Surrounding Application and Browser Extension

_For the coding agent building the interface, local host application, and Chrome extension. Written against `answer-cache-agent` v0.1 (all four build phases complete, 2026-09-22): `handle_event`, the event contract, the CLI harness, and the importer are implemented and tested. Copy `fixtures/*/events.jsonl` as your first integration test scripts._

## 1. What you are integrating with

`answer_cache_agent` is a **Python library** (LangGraph inside) that, given a questionnaire's questions and context, returns grounded answer *templates* — symbolic text with `{{variable_id}}` placeholders — and learns from the user's choices. It runs entirely on the user's machine and talks directly to the user's model provider with the user's own key.

| The agent does | The agent does not |
|---|---|
| Validate and organize form context you send | Read the page; you extract questions and constraints |
| Retrieve relevant templates/evidence semantically from its own SQLite file | Submit forms, click, or decide whether to overwrite a field |
| Generate, validate, cache, and rank candidate templates | Resolve `{{placeholders}}` for display — you render locally with the private values |
| Record exposure, selection, rejection, edits, approvals; update ranking | Infer any of those events — you must report them explicitly |
| Enforce its own budget and ledger | Host an HTTP server, manage windows, or store your UI state |

Everything the agent needs from you goes through **one function call per user interaction** carrying a JSON event, and everything it gives back is **one JSON result**. There is no streaming and no long-lived process requirement: each event is a bounded invocation.

## 2. Process topology (recommended)

```text
Chrome extension ──(native messaging or localhost HTTP, yours)──▶ Local host app (yours)
                                                                       │ in-process Python call
                                                                       ▼
                                                              answer_cache_agent.graph.Agent(runtime).handle_event(event)
                                                                       │
                                                                       ├── <data_dir>/answer_cache.db   (SQLite: app data + vector index + LangGraph checkpoints)
                                                                       └── provider API (OpenAI / Anthropic) using the user's key
```

- **You own the transport.** The agent exposes a Python function, not a port. Wrap it in whatever your host uses (a `localhost` HTTP shim, native messaging host, or a subprocess). Keep the wrapper thin: deserialize JSON → call → serialize JSON. Do not add business logic there.
- **One agent instance per host process.** Constructing the runtime loads a ~65 MB local embedding model once (~6 s cold). Do not construct per request.
- **Serialize calls per `session_id`.** SQLite handles cross-process safety, but the agent's revision check will reject interleaved events on the same form (see §5). A per-session queue in your host is the simplest fix.
- A subprocess alternative is `answer-cache-agent events.jsonl --db <path> --scope <scope> --bindings bindings.json --json` (see `README.md`); the in-process call is preferred because it avoids reloading the embedding model per call.

## 3. Trust boundary — the part that must not be gotten wrong

There are exactly **two input channels**, and they are not interchangeable:

| Channel | Carries | Goes to the model? | Checkpointed/logged? |
|---|---|---|---|
| **Event payload** (JSON, validated against `schemas/Event.schema.json`) | Questions, constraints, sanitized page text, hints, rules, feedback | Parts of it, yes | Yes |
| **Runtime dependencies** (Python object you construct once per process) | Database path, provider credentials, model-role config, **private variable bindings** | **Never** | **Never** |

Rules for the extension and host:

1. **Never put an API key, a private value, or a file path in an event payload.** The schema rejects unknown fields (`additionalProperties: false`), but a key smuggled inside `page_context` would pass validation and reach the model. Treat every payload field as "this may be sent to a third-party provider".
2. **Bindings do enter the agent process**, via runtime deps, because the agent must run length/format checks *after* substitution (PRD §8). They are held in memory only; the agent asserts they are absent from every outbound payload and from its telemetry (`rendering.find_leaks`).
3. **`page_context` must already be sanitized and disclosure-approved by you.** The agent treats it as untrusted data and instructs the model to ignore instruction-like text inside it, but that is defense in depth, not a filter. If a page contains something the user would not want sent to a provider, do not send it.
4. **Variable descriptors are model-visible; values are not.** Register variables through ingestion (§9) with a `safe_description` that gives the model enough meaning to place the variable ("user-approved motivation statement for engineering roles"), never the value.
5. **The model cannot reason about hidden values.** Descriptors-only is a deliberate v1 decision. If a question needs the *content* of a private value (e.g. "do you have more than 5 years of X?"), the agent returns `needs_information` / `hidden_value_reasoning`. Your UI should let the user answer manually or expose the fact explicitly.

Runtime deps shape (Python):

```python
from answer_cache_agent.graph import Agent, RuntimeDeps
from answer_cache_agent.providers import Credentials, ModelRef, ModelRoles

runtime = RuntimeDeps(
    db_path="/home/user/.local/share/answer-cache/answer_cache.db",
    credentials=Credentials(openai_api_key=..., anthropic_api_key=...),   # from your keychain, per call is fine
    model_roles=ModelRoles(routine=ModelRef("openai", "gpt-4o-mini"), advanced=ModelRef("anthropic", "claude-sonnet-5")),
    bindings={"v17": "…private text…", "phone": "555-0100"},             # only variables in this scope
    config_path=None,                                                     # defaults to the packaged config.yaml
)
agent = Agent(runtime)              # once per process: opens the DB, loads the embedding model, compiles the graph
result: dict = agent.handle_event(event_json)
```

`Agent` is not thread-safe; call it from one thread (or one per-session queue drained by one worker). To rotate bindings or credentials between calls, assign `agent.rt.bindings = {...}` / `agent.rt.credentials = Credentials(...)`; do not rebuild the `Agent` (that reloads the embedding model).

## 4. The event contract

All ten public schemas are in `schemas/*.schema.json` (JSON Schema 2020-12, generated from the Pydantic models in `answer_cache_agent/contracts.py`). Generate TypeScript types from them (`json-schema-to-typescript` or similar) rather than hand-writing.

### Envelope (`Event.schema.json`)

```json
{
  "event_id": "8b1f…-uuid",          // unique per attempt; re-sending the same id replays the stored result
  "session_id": "form-…-uuid",       // one per form instance (tab + URL + your form fingerprint)
  "scope_id": "user-default",        // data partition: templates/evidence/variables are only visible within a scope
  "type": "prepare_form",
  "expected_revision": null,         // null only on the first prepare_form; afterwards the last Result.revision
  "payload": { … }
}
```

### Event types

| `type` | Payload schema | Paid model call? | Typical statuses |
|---|---|---|---|
| `prepare_form` | `PrepareFormPayload` | **Never** | `ready` |
| `generate_initial` | `GenerateInitialPayload` | Yes, when not cached | `ready`, `partial`, `needs_information`, `budget_exhausted`, `failed` |
| `get_candidate` | `GetCandidatePayload` | **Never** (a cache miss returns `partial` with an empty list; it does not generate) | `ready`, `partial`, `stale_context` |
| `regenerate_question` | `RegenerateQuestionPayload` | Yes | `ready`, `needs_feedback`, `needs_information`, `budget_exhausted` |
| `record_feedback` | `RecordFeedbackPayload` | **Never** | `ready` |
| `update_form` | `PrepareFormPayload` | **Never** | `ready` |

### Minimal examples

**`prepare_form`** — send as soon as you have extracted the form. Include fields you already auto-filled (`prefilled: true`) so the agent skips them; include the template id you filled them from if you know it.

```json
{
  "questions": [
    {"id": "q1", "text": "Why do you want to work here?", "constraints": {"max_length": 1500}},
    {"id": "q2", "text": "Are you willing to relocate?", "constraints": {"max_words": 50}},
    {"id": "q3", "text": "Full name", "prefilled": true}
  ],
  "page_url": "https://jobs.example.edu/apply/123",
  "page_title": "Software Engineer, Learning Platform",
  "page_context": "Sanitized job description text you have approved for disclosure…",
  "hints": [{"dimension": "role_family", "value": "agent_engineering", "source": "user"}],
  "rules": [{"id": "edu", "match_field": "page_url", "pattern": "\\.edu/", "dimension": "sector", "value": "education"}]
}
```

**`generate_initial`** — the user pressed "help" on q1; you also authorize pre-generation for q2. The agent returns q1's two variants for immediate display and caches q2's.

```json
{"target_question_ids": ["q1"], "authorized_question_ids": ["q2"], "limits": {"max_cost_usd": 0.10}}
```

**`get_candidate`** — the user asks for the concise version; no model call.

```json
{"question_id": "q1", "variant": "concise"}
```

**`record_feedback`** — report exposure the moment candidates are rendered, then outcomes as they happen. One event per fact.

```json
{"outcome": "shown", "shown": ["cand-a", "cand-b"], "alternatives": ["cand-c"]}
{"outcome": "selected", "candidate_id": "cand-a"}
{"outcome": "edited", "candidate_id": "cand-a", "edited_body": "…the text the user actually submitted, unrendered if you can…"}
{"outcome": "rejected", "candidate_id": "cand-b", "reasons": ["too_long", "wrong_emphasis"], "free_text": "focus on the platform work"}
{"outcome": "approved", "candidate_id": "cand-a", "approve_as_template_id": "T_motivation_edu_1"}
```

**`regenerate_question`** — pass the rejections you have collected; the agent uses them in the prompt and, once a whole targeted set is rejected, runs a separate diagnosis before the next attempt.

```json
{"question_id": "q1", "rejected": [{"candidate_id": "cand-b", "reasons": ["too_generic"]}]}
```

### Result (`Result.schema.json`)

```json
{
  "event_id": "…", "status": "ready", "revision": "rev-3f9a…",
  "candidates": [ {"id": "cand-a", "question_id": "q1", "variant": "standard",
                   "body": "{{v17}} I'm drawn to teams that ship evaluation tooling with agents.",
                   "variables": ["v17"], "evidence_refs": ["E3"], "template_refs": ["T_B"],
                   "status": "valid", "form_revision": "rev-3f9a…", "validation": {}, "self_report": {"confidence": 0.86},
                   "ranking": {"score": 0.71, "semantic": 0.79, "context": 0.75, "quality": 0.5, "preference": 0.5, "policy_version": "1"}} ],
  "cached": {"q2": ["cand-c", "cand-d"]},
  "evidence_refs": ["E3"],
  "unresolved": [{"question_id": "q4", "reason": "insufficient_evidence", "needed": "any approved statement about management experience"}],
  "usage": {"calls": 1, "tokens": 2310, "cost_usd": 0.0012, "uncertain": 0},
  "next_action": null,
  "diagnostics": []
}
```

`body` is **unrendered**. Render it locally (§7) before showing it.

## 5. Session and revision protocol

1. **`session_id`**: mint one UUID per form instance and keep it for the life of that tab/form. Reuse it across all events for that form. The agent keeps the form's state, candidates, and LangGraph checkpoint under it.
2. **`event_id`**: mint a fresh UUID per *attempt*. If your call times out or the host crashes mid-call, **retry with the same `event_id`**: the agent replays the stored result if the event completed, and never double-charges or double-applies feedback. Use a new id only for a genuinely new action.
3. **`expected_revision`**: every result carries `revision`. Send it back on the next event. If the form changed underneath (another tab, a page re-render you already sent as `update_form`), the agent replies `stale_context` and writes nothing; refresh your view of the form, send `update_form`, then retry the action with the new revision.
4. **`update_form`**: send when questions, constraints, hints, or page context change. The agent recomputes the revision and marks candidates from the old revision `stale`; they are never returned again as valid.
5. **Ordering**: send events for one session strictly in order (queue them). Events for different sessions may run concurrently.

## 6. Exposure and feedback — what to report, and what never to infer

The learning system is only as honest as your reports. The agent will **not** infer anything you do not send.

| Do | Don't |
|---|---|
| Send `shown` with the exact ids rendered, in display order, every time the visible set changes | Assume a generated candidate was seen |
| Send `rejected` only when the user explicitly rejects (a thumbs-down, "not this one", dismissing a specific candidate) | Treat "user asked for more" as rejection of the hidden ones, or "left unused" as rejection |
| Send `edited` with what the user changed, when they modify a candidate before using it | Collapse an edit into a selection or a rejection |
| Send `selected` when the user inserts a candidate into the field | Send `approved` implicitly — approval is a deliberate "save this wording for future forms" action |
| Define your own rejection-reason vocabulary and pass codes as strings | Expect the agent to validate codes: it stores, forwards, and learns from them opaquely |

Suggested starter codes (yours to change; the agent is vocabulary-agnostic): `inaccurate`, `too_long`, `too_short`, `wrong_emphasis`, `wrong_tone`, `irrelevant`, `too_generic`, `missing_detail`.

Approval promotes a candidate into the reusable template collection under the id you supply. It records *preference* provenance; it does not make the text a factual source (there is no implicit "approve as evidence"; that would be a separate operation if ever added).

## 7. Rendering `{{placeholders}}` locally

- Syntax: `{{identifier}}` where identifier matches `[A-Za-z_][A-Za-z0-9_]*`, optional inner whitespace. Nothing else — no filters, expressions, or defaults. It is data, not a template language.
- Every `body` you receive has already passed an authorization check: it references only variables permitted for that question and scope. If you nonetheless see an id you have no binding for, treat the candidate as unusable and report it (`diagnostics` will tell you if the agent knows why).
- The agent runs `max_length`/`max_words` checks *after* substitution on its side (it has the bindings via runtime deps) and marks violations in `validation`. Still re-check after your own render — your bindings are authoritative.
- If your host is Python, import and reuse: `from answer_cache_agent.rendering import render, referenced_variables, check_constraints`. If not, the regex above is the whole spec.

## 8. Status handling

| `status` | Meaning | What the UI should do |
|---|---|---|
| `ready` | Everything requested is available | Show `candidates`; note `cached` for other fields |
| `partial` | Some questions have candidates, others are in `unresolved` | Show what exists; surface each `unresolved.reason`/`needed` |
| `needs_information` | Nothing usable; the bundle lacks support or needs a hidden value | Show `unresolved[].needed`; offer manual answer or "add information" |
| `needs_feedback` | The targeted candidate set is exhausted without structured reasons | Ask the user what is wrong (reason codes + free text), then `regenerate_question` with `rejected[]` filled |
| `budget_exhausted` | A configured or request-level limit stops further paid calls | Show `usage`; offer to raise the limit for this request (`limits`) or stop |
| `stale_context` | `expected_revision` did not match | Re-extract, `update_form`, retry (§5) |
| `failed` | Provider error, persistence error, or an uncertain paid call that will not be auto-retried | Show `diagnostics`; a retry needs a **new** `event_id` and, for uncertain calls, an explicit user OK (the agent never re-sends a paid request whose outcome it did not observe) |

`usage.uncertain > 0` means a paid request was sent but its result never arrived; the tokens are counted at estimate, not zero.

## 9. Ingesting the user's existing material

The agent ships a narrow JSONL importer (`python -m answer_cache_agent.ingest records.jsonl --db … --scope …`) and a repository API. Records:

```jsonl
{"kind":"dimension","id":"role_family","label":"Role family"}
{"kind":"value","id":"agent_engineering","dimension_id":"role_family","label":"Agent engineering"}
{"kind":"variable","id":"v17","safe_description":"User-approved motivation statement for agent-engineering roles","value_type":"text","permitted_use":"verbatim"}
{"kind":"evidence","id":"E3","locator":"https://example.org/eng-blog","version":"2026-08-01","excerpt":"We ship evaluation tooling with every agent.","disclosure":"model_visible","approved_by":"user","approved_at":"2026-09-01"}
{"kind":"template","id":"T_B","intent":"motivation","aliases":["Why do you want to work here?"],"body":"{{v17}} I'm drawn to teams that ship evaluation tooling alongside agents.","variables":["v17"],"evidence":["E3"],"context":[{"dimension":"role_family","value":"agent_engineering","mode":"applies"}],"approved_by":"user","approved_at":"2026-09-01","disclosure":"model_visible"}
```

- `approved_by`/`approved_at`/`disclosure` are mandatory on `template` and `evidence`; there is no "import as approved by default".
- Variable **values** are never in this file. They live in your private store and reach the agent only as runtime bindings.
- Your settings UI is the natural owner of dimensions, values, variables, and hint rules. Keep them user-defined; the agent has no built-in taxonomy and must not be given one.
- Do not build document parsing/chunking around this. If evidence is long, the user approves an excerpt.

## 10. Context hints — deterministic only

Hints reach the agent three ways, all deterministic: `hints[]` on the form or on individual questions (your UI or already-populated data), user-defined `rules[]` (regex over `page_url`/`page_title`/`question_text`), and explicit user selections (`source: "user"`). The model never proposes classifications. A dimension with no hint is *unknown* — it never counts against a template — so it is better to send nothing than to guess.

## 11. Budget

Every paid call checks: candidate counts, questions per batch, tokens, per-operation call count, cumulative session cost/tokens, and retry count. Defaults are in `answer_cache_agent/config.yaml` (session cap $0.50, 150k tokens). A request may tighten them with `limits`; it cannot loosen the session cap. Cost is a guard computed from a static pricing table, not the provider's bill. Show `usage` in your UI; it is how the user sees what pre-generation cost them.

## 12. Checklist before you ship the integration

- [ ] Types generated from `schemas/`, not hand-written.
- [ ] No credential, private value, or path ever placed in a payload; keys and bindings go through runtime deps.
- [ ] `page_context` is sanitized and user-approved before sending.
- [ ] One `session_id` per form, one `event_id` per attempt, retries reuse the `event_id`.
- [ ] `expected_revision` echoed from the last result; `stale_context` handled.
- [ ] `shown` reported on every render; `rejected` only on explicit rejection; `edited` distinct from both.
- [ ] `{{placeholders}}` rendered locally; post-render length re-checked.
- [ ] Every status in §8 has a UI path, including `needs_feedback` collecting structured reasons.
- [ ] Events per session are queued in order.
- [ ] Agent runtime constructed once per host process.

## 13. Current build status of the agent (so you know what you can run today)

| Layer | Status |
|---|---|
| Contracts + JSON schemas (`contracts.py`, `schemas/`) | Done — build against these now |
| Repository, SQLite schema, vector index, ranking (`repository.py`, `db.py`, `ranking.py`) | Done, tested |
| Rendering + leak check (`rendering.py`) | Done, tested |
| Provider adapters (OpenAI, Anthropic, Fake) + versioned prompts | Done; real adapters constructed but not yet exercised against live APIs |
| `Agent.handle_event` / LangGraph nodes / router / checkpointer (`graph.py`, `budget.py`) | Done; 13 end-to-end scenario tests with a scripted provider |
| CLI harness (`answer-cache-agent`), JSONL importer, two fixture domains, evaluation report | Done; `--demo` runs offline with a success marker |

Two behaviors worth knowing that the tests pin down: (1) if the host process dies mid-`generate_initial`, re-sending the **same** `event_id` resumes from the LangGraph checkpoint and does not re-pay for questions already written through; (2) `regenerate_question` returns only the new batch in `candidates` and lists earlier still-valid ones in `cached[question_id]`.
