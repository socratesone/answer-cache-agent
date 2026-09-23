# §14 Design Review — Questionnaire Completion Agent

_Status: **decided 2026-09-21** — see the Owner Decisions block. Sections below are the original proposals; where a decision changed a recommendation the section is marked SUPERSEDED and the decision block governs. Responds to `PRD.md` §14 (v0.1)._

## Owner decisions (2026-09-21)

| # | Decision | Effect on the proposal below |
|---|---|---|
| Q1 | **Accept.** Flat dimensions + values; `applies`/`requires`; missing = unknown; no hierarchy. Keep migration additive. | As written. `parent_id` column dropped from v1 DDL (add later if usage demands; additive). |
| Q2 | **Modify.** Context construction is fully deterministic: page/form state from the app (including fields the app already populated), explicit user input, and user-defined deterministic rules. **No model-suggested hints.** | Option B only; Option C removed. `confidence`/`confirmed` columns dropped; `source ∈ {caller, rule, user}`. |
| Q3 | **Accept with spike.** `sqlite-vec` + `fastembed` local ONNX in the same SQLite file, scope isolation, hash embedder for tests — behind `Embedder` and `VectorStore` protocols. Spike first; stop and report on material problems. **Do not embed metamodel labels** in v1. | As written. Spike: `scripts/spike_retrieval.py`. |
| Q4 | **Accept.** Deterministic, no LLM, every component sourced and inspectable. Weights/constants are defaults. | As written; constants move to `config.yaml`. |
| Q5 | **Modify.** Deterministic checks always. **No semantic evaluator on initial generation or on the first targeted regeneration.** Evaluator runs only when the targeted candidate set has been exhausted through explicit rejection; it receives question, context, rejected candidates, their evidence bundles, structured rejection reasons, optional free text, and its output is a *diagnosis* fed into the next generation attempt. Structured rejection metadata is part of the agent contract; vocabulary is not hard-coded in the graph. Self-assessment may remain as metadata but never triggers a paid call. | Trigger list and 0.7-threshold gate SUPERSEDED. Acceptance gate becomes: deterministic pass → `valid`; deterministic fail → `invalid`; generator abstention → `needs_information`. |
| Q6 | **Change to descriptors only.** No derived facts, no local comparison functions. If a hidden value's meaning is needed, the user exposes the fact explicitly, encodes it in a template, or answers manually. Document that variables protect substitutable text (names, contact details, identifiers, proprietary fragments), not hidden computation. | Option A. `derived_facts` removed from the variable record and the ingest format. Detection of "needs hidden-value reasoning" relies on the generator returning a structured `needs_information` abstention (PRD §8 permits "return a request for information"). |
| Q7 | **Accept.** SqliteSaver, session = thread, write-through candidates, `event_id` idempotency, optimistic revision, ledger `reserved/confirmed/uncertain`, no auto-retry of uncertain, no bindings/credentials in checkpoints. | As written. |
| Q8 | **Accept with terminology.** Three lanes, structurally distinct: *source/factual evidence*, *feedback/preference evidence*, *approved template*. Approval proves preference, never factual truth. A future `approve_as_source` would be a separate deliberate operation. | As written; terminology adopted in code and docs. |
| Q9 | **Modify.** All tunables in **one validated YAML file**; structural invariants stay in code. Review defaults stand unless superseded above. | The "six exposed controls" idea is replaced by one `config.yaml` validated by a Pydantic model. |
| Q10 | **Accept.** Narrow JSONL ingest + repository API. No parsing/chunking/fetching. | As written, minus `derived_facts`. |

**Implementation notes added after the Phase 4 evaluation (within the accepted Q4 structure, no owner re-decision needed):** (a) `requires` values count toward context match as well as filtering; (b) semantic similarity is min-max normalized across each question's retrieved set, raw value recorded alongside; (c) the global preference key is used only for context-free forms — a known-but-sparse context gets the neutral prior, so selections never leak into unrelated contexts. Each is a sourced, inspectable component change, not a new signal.

**Consequences recorded as known limitations:** (i) factual support on the initial batch is checked only by deterministic evidence-linkage (every candidate must cite ≥1 ref from its own bundle) plus the generator's self-report, not by an independent evaluator; (ii) hidden-value questions are detected by generator abstention, not deterministically.

Each question below gives the viable options, their implications, a recommendation, and a concrete example where the abstraction would otherwise stay vague. The last section separates **blocking** decisions (must be settled before the schema/graph is written) from **tunable** defaults (ship with a value, adjust later without restructuring).

Environment facts that shaped the recommendations: Python 3.10; `sqlite-vec` 0.1.9, `faiss-cpu` 1.7.4, `onnxruntime` 1.23, `numpy`, `pydantic` 2.x, `langgraph` and `langchain-openai` are already installed; `langgraph-checkpoint-sqlite`, `langchain-anthropic`, and `fastembed` are not (all pip-installable). SQLite is 3.41.

---

## Q1. Concrete metamodel

### Options

**A. Flat dimensions + values, many-to-many assignments (PRD proposal).**
Three tables: `dimension`, `value(dimension_id)`, `assignment(subject_type, subject_id, value_id, mode, source, confidence)`. A subject (form, question, template) may carry any number of values from any dimension, including several values from the same dimension.
- Implementation: trivial SQL; context match is set arithmetic.
- Maintenance: users add dimensions/values as rows; no code change.
- Limits: no "education ⊂ public_sector" inference. Overlap is expressed by assigning both values.

**B. Free tags (one namespace, no dimension).**
A single `tag` table. Simpler still, but "missing hint = unknown, not mismatch" needs a dimension to be well-defined (you can only say "this axis is unknown" if axes exist). Ranking also needs to know that `education` and `general` are alternatives on the same axis, not independent facts.

**C. Flat + optional parent value (limited hierarchy).**
Option A plus a nullable `value.parent_id`. Matching walks up the chain. Adds one join and a cycle guard; useful only when a user actually models a taxonomy.

### Recommendation: **A**, with two explicit rules

1. **Applicability vs. restriction are different `mode`s on the assignment row.**
   - `mode = applies`: soft context. Contributes to the contextual-match score only.
   - `mode = requires`: hard restriction. The template is *ineligible* unless the active form context contains that value. Evaluated before scoring (PRD §7 ranking property 1).
   - There is no `excludes` mode in v1: "requires X" on a template already excludes forms without X, and negative rules invite taxonomy games the PRD forbids.
2. **Cardinality:** any subject may have 0..n values per dimension. Zero values on a dimension means "unknown / applies to all" — never a mismatch. A template with `requires` on two dimensions must satisfy both.

Hierarchy (C) is deferred; the schema leaves a nullable `parent_id` column unused so adding it later is additive.

### Proposed schema (SQLite)

```sql
CREATE TABLE dimension (id TEXT PRIMARY KEY, label TEXT NOT NULL, scope_id TEXT NOT NULL);
CREATE TABLE value_ (id TEXT PRIMARY KEY, dimension_id TEXT NOT NULL REFERENCES dimension(id),
                     label TEXT NOT NULL, parent_id TEXT NULL);
CREATE TABLE assignment (
  subject_type TEXT NOT NULL CHECK (subject_type IN ('form','question','template')),
  subject_id   TEXT NOT NULL,
  value_id     TEXT NOT NULL REFERENCES value_(id),
  mode         TEXT NOT NULL CHECK (mode IN ('applies','requires')),
  source       TEXT NOT NULL CHECK (source IN ('caller','rule','model','user')),
  confidence   REAL NOT NULL DEFAULT 1.0,
  confirmed    INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (subject_type, subject_id, value_id)
);
```

### Example (the PRD's own data)

| Subject | Assignment |
|---|---|
| Template A | `applies role_family=full_stack` |
| Template B | `applies role_family=agent_engineering` |
| Template C | `applies sector=education` |
| Template D | `requires sector=education` (a template that literally names a school district) |
| Form F | `applies role_family=agent_engineering`, `applies sector=education` |

For Form F: A, B, C, D are all eligible on `requires` (only D has one, and it is satisfied). Contextual match: A matches 0/2 known dimensions, B 1/2, C 1/2, D 1/2. A form tagged only `role_family=full_stack` makes D ineligible and leaves C's `sector` unknown (neutral), not mismatched.

---

## Q2. Active contextual hints — SUPERSEDED (Option B only; no model suggestions)

### Options

**A. Caller-supplied only.** The surrounding app sends `hints: [{dimension, value, source, confidence}]` on `prepare_form` / `update_form`. Agent stores them verbatim.
- Cheapest. Puts the whole burden on the app's UI.

**B. A + user-maintained deterministic rules.** A `hint_rule` table: `(scope_id, match_field, pattern, dimension_id, value_id)`; e.g. `page_url ~ "\.edu" → sector=education`. Rules run in Prepare, cost nothing, and produce `source=rule` assignments.
- Small: one table, one regex loop. Lets a user teach the system once.

**C. B + model-suggested assignments.** During an *authorized* generation call, the prompt may also return `suggested_hints`. Stored as `source=model, confirmed=0`.
- No extra call (piggybacks on generation) but adds schema to the structured output and a confirmation loop in the app.

### Recommendation: **B now, C as a recorded-but-inert output**

- Prepare applies caller hints and rule hints. Both are `confirmed=1` (the user authored the rule or the app asked).
- Generation *may* emit `suggested_hints`; they are persisted with `confirmed=0` and returned in the result for the app to confirm. **Unconfirmed hints never affect eligibility or ranking.** This satisfies "must users confirm inferred assignments? — yes", keeps zero paid calls in Prepare, and costs nothing if the app ignores the field.
- Uncertainty representation: `confidence` on the row plus `confirmed`. Confidence is informational in v1 (ranking uses only confirmed rows with weight 1); it exists so a later version can weight without a migration.

Conflict rule: if caller and rule disagree on the same dimension (`sector=education` from caller, `sector=general` from rule), both are stored; caller wins for ranking (`source` precedence `user > caller > rule > model`). The conflict is reported in the result's `diagnostics`.

---

## Q3. Semantic retrieval implementation

### Options — vector store

| | A. `sqlite-vec` (installed) | B. FAISS flat index (installed) | C. NumPy brute force |
|---|---|---|---|
| Storage | `vec0` virtual table in the *same* SQLite file as everything else | Separate `.index` file + id map | Embeddings as BLOBs in SQLite, scored in Python |
| Delete/update | `DELETE`/`INSERT` rows; transactional with app data | `remove_ids` on IDMap, no transactions; rebuild-on-delete for safety | Plain row ops |
| Scale | Brute-force KNN; fine to ~100k rows × 384 dims | Millions | ~20k rows before latency is noticeable |
| Footprint | ~1 MB extension, Apache-2/MIT | ~30 MB wheel, MIT | zero |
| Filtering | Metadata filter *after* KNN (or partition by scope via separate tables); needs `k` overshoot | Post-filter | Trivial pre-filter |
| Rebuild | `DELETE FROM vec WHERE embedding_version != ?` then re-embed | Drop file, re-add | Same as A |

### Options — embedding model

| | Local ONNX (e.g. `bge-small-en-v1.5`, 384-d, ~65 MB) via `fastembed` | Provider API (OpenAI `text-embedding-3-small`, Anthropic has none) |
|---|---|---|
| Privacy | Text never leaves the machine; satisfies §8 "remote embeddings if ever introduced" by not introducing them | Every indexed template body and every question is transmitted; requires the disclosure filter on the indexing path too |
| Cost | Free, ~5 ms/record on CPU | Paid; counts against budget; an index rebuild is a bill |
| Install | One-time model download (~65 MB) on first use; offline after | None |
| Quality | Adequate for short paraphrase matching; the ranking formula (Q4) carries context, not the embedding | Better on long text; irrelevant here |
| Licensing | Apache-2 (fastembed), MIT (bge) | n/a |

### Recommendation: **A + local ONNX via `fastembed`**, behind an `Embedder` protocol

- One SQLite file holds dimensions, templates, candidates, ledger *and* vectors — one transaction boundary, one backup, one deletion path (PRD §12 retention).
- Store `embedding_model`, `embedding_dim`, `index_version` on every vector row; retrieval filters on the active version so a model change can never mix spaces (§7 index maintenance).
- Scope enforcement: one `vec0` table per `scope_id` is the simplest hard boundary and avoids overshoot-and-filter leakage across scopes. Cardinality of scopes is small (a user, an org).
- Corpus target for v1: **≤ 50k template/evidence records per scope**, documented. Beyond that, swap the store behind the same `VectorStore` protocol (FAISS is already installed and fits the protocol).
- Tests use a deterministic `HashEmbedder` (token-hash bag → 384-d, normalized) so the suite is offline and needs no model download. The paraphrase acceptance test runs with the real embedder under a `--with-model` marker.

Concrete: question "Why are you interested in this position?" embeds close to the stored intent alias "Why do you want to work here?" (cosine ≈ 0.8 with bge-small); the hash embedder will *not* find it — hence the marker.

---

## Q4. Ranking and correlation updates

### Options

**A. Smoothed contextual outcome counts (Beta posterior mean).** Per `(template, context_key)`: `pref = (sel + α) / (sel + rej + α + β)`. Cold start returns the prior mean. Sparse contexts back off to coarser keys.

**B. Capped additive facet scores.** Each dimension value contributes `±δ` per event to a per-`(template, value)` score, clamped to `[-c, +c]`. Simple but dimensions interact additively — a template loved under `sector=education` leaks into every education form regardless of role.

**C. Joint-context statistics with fallback (A on the full key, backing off to single-value keys, then global).** Same as A with a defined back-off ladder.

### Recommendation: **C** (which is A with an explicit back-off), inside a fixed-weight linear combination with a hard cap on preference

```text
eligible = [t for t in retrieved if scope_ok(t) and approved(t) and requires_satisfied(t, form_ctx)]

for t in eligible:
    sem   = cosine(q_vec, t_vec)                          # 0..1, from vector store
    ctx   = ctx_match(t, form_ctx)                        # below
    qual  = last_eval_score(t) if evaluated(t) else 0.5   # 0..1, neutral if never evaluated
    pref  = preference(t, form_ctx)                       # below, 0..1
    fresh = 1.0 if source_current(t) else 0.0             # hard gate, not a weight (stale evidence → ineligible above)

    score = 0.40*sem + 0.25*ctx + 0.20*qual + 0.15*pref
    components[t] = dict(sem=sem, ctx=ctx, qual=qual, pref=pref, weights=W, policy_version=P)

ctx_match(t, form_ctx):
    known = {d for d in form_ctx.dimensions if form_ctx.has_value(d)}     # missing hints excluded from denominator
    if not known: return 0.5                                              # nothing known → neutral
    hits = sum(1 for d in known if t.values(d) & form_ctx.values(d))
    miss = sum(1 for d in known if t.values(d) and not (t.values(d) & form_ctx.values(d)))
    # a template that says nothing about a known dimension is neutral on it
    return 0.5 + 0.5 * (hits - miss) / len(known)   # clamp 0..1

preference(t, form_ctx):
    # back-off ladder: full joint key → each single value → template global
    for key in [joint_key(form_ctx), *single_keys(form_ctx), GLOBAL]:
        s = stats(t, key)                     # decayed sel, rej, edit counts
        n = s.sel + s.rej + s.edit
        if n >= MIN_N or key is GLOBAL:
            wins = s.sel + 0.5*s.edit         # an edit is half a selection
            return (wins + ALPHA) / (n + ALPHA + BETA)
    # unreachable: GLOBAL always returns
```

Update rule (Persist/Learn, idempotent on `event_id`):

```text
on feedback(event_id, candidate, outcome, context_snapshot):
    if seen(event_id): return
    key_set = [joint_key(context_snapshot), *single_keys(context_snapshot), GLOBAL]
    for key in key_set:
        s = stats(candidate.template, key)
        s.decay(now)                          # counts *= 0.5 ** (Δt / HALF_LIFE)
        if outcome == selected: s.sel += 1
        if outcome == rejected: s.rej += 1
        if outcome == edited:   s.edit += 1
        # exposure without outcome updates s.shown only; never sel/rej
    mark_seen(event_id, policy_version)
```

Defaults: `ALPHA=1, BETA=1` (uniform prior → 0.5 cold start), `MIN_N=3`, `HALF_LIFE=90d`.

Why this satisfies the PRD properties:
- **Popularity cannot override restriction/support**: `requires` and approval are filters, `qual` is a separate component, and `pref` is capped at a 0.15 weight — the most-selected template in the world moves the score by ≤0.15.
- **Missing hints are unknown**: excluded from the `ctx_match` denominator; `preference` backs off to single-value keys so a form with one known dimension still gets that dimension's statistics.
- **Overlapping dimensions**: the joint key captures interaction when data exists (`{agent_engineering, education}` ≠ `{full_stack, education}`); when it is sparse the single-value keys give a sensible estimate; the global key is last resort.
- **Inspectable**: every returned candidate carries `components`, the weights, and `policy_version`; the eval report replays events with `pref` weight 0 as the fixed baseline.
- **Learning off**: `RankingPolicy(learning_enabled=False)` sets the `pref` weight to 0 and skips stats updates; feedback events are still written.

Example: after three selections of Template B on `{agent_engineering, education}` forms, `pref(B, joint)` = (3+1)/(3+2) = 0.8; on a `{full_stack}` form the joint key has n=0, `full_stack` single key has n=0, so B falls to GLOBAL — where its three wins still count, but B's `ctx_match` on that form is 0.0 (it *contradicts* the known `role_family`), which costs it 0.25 of score against A's 0.5.

---

## Q5. Evaluation architecture — SUPERSEDED (evaluator only after targeted-set exhaustion; see decisions)

### What each layer can and cannot detect

| Layer | Detects | Cannot verify | Cost |
|---|---|---|---|
| Deterministic checks | JSON shape, candidate count, variable IDs ∈ authorized set, question linkage, scope, length/format *after* substitution, banned-pattern leaks (private value strings in outbound payload) | Relevance, factual support, whether a "concise" variant dropped a qualification | 0 |
| Generator self-assessment (`confidence`, `unsupported_claims[]`, `dropped_qualifications[]` in the same structured output) | Cases where the model *knows* it is stretching — surprisingly useful for abstention | Anything the generator is wrong about; not independent | 0 extra calls, ~10% more output tokens |
| Separate semantic evaluator (advanced role, one batched call per batch) | Relevance, evidence support (given the same evidence bundle), contextual fit, completeness, qualification preservation across standard→concise | Ground truth outside the evidence bundle; it is still an LLM opinion | +1 paid call per batch; ~60% of the generation input tokens |

### Options

**A. Deterministic + self-assessment only.** Cheapest; the "evaluation" node would be honest about being mostly structural. Weak on the PRD's semantic evaluation bullet.

**B. Always run the separate evaluator.** Fully satisfies §9; doubles call count on every generation.

**C. Deterministic always; self-assessment always; semantic evaluator conditionally.** Trigger the evaluator when any of: (i) operation is `regenerate_question` (the user already disliked something), (ii) any candidate self-reports `confidence < 0.7` or a non-empty `unsupported_claims`, (iii) a question's evidence bundle has < 2 supporting records, (iv) the form field has a hard length limit and the concise variant is within 10% of it. Otherwise skip.

### Recommendation: **C**, with this acceptance gate

```text
status per candidate:
  deterministic FAIL                → invalid  (never returned; retained as diagnostic)
  deterministic PASS, no evaluator  → valid    (self-assessment attached, labeled "generator_self_report")
  evaluator ran, score ≥ 0.7        → valid    (evaluation attached, labeled "evaluator:<model>")
  evaluator ran, score < 0.7        → valid_with_findings (returned, ranked below, findings attached)
  evaluator finds unsupported claim → invalid  (abstention recorded with gap reason)

batch status:
  all target questions have ≥1 valid → ready
  some do                            → partial
  none, because evidence missing     → needs_information
```

Both roles may point at the same model; escalation is a config lookup, not a code path. The evaluator sees exactly the evidence bundle the generator saw (no fresh retrieval), so it cannot "know more" than the generator — it can only judge consistency with the bundle, which is the honest claim.

---

## Q6. Hidden-value reasoning — SUPERSEDED (Option A, descriptors only; see decisions)

### Options

**A. Safe descriptors only.** The model gets `{id, safe_description, value_type, permitted_use}`. It can *place* a variable, never reason about its contents.

**B. A + locally computed derived facts.** A variable definition may declare `derived_facts`: named, user-approved, locally computed booleans/enums/numbers about the private value that *are* disclosable. Example: `years_python` (private: `7`) declares `derived_facts: {years_python_gte_5: true, years_python_band: "5-10"}`. Computed by local code from the binding at Prepare time; only the declared facts enter the outbound payload.

**C. B + `needs_information` when neither suffices.** If the question needs a comparison/summary over a hidden value and no derived fact covers it, the candidate is an abstention with a structured gap.

### Recommendation: **C**

Two worked cases:

**Answerable by substitution:** "Why do you want to work for our organization?" → evidence: approved template B; variables: `v17` (safe_description "user-approved motivation statement for agent-engineering roles", permitted_use verbatim). Candidate: `"{{v17}} I'm particularly drawn to the way your team ships evaluation tooling alongside agents."` — the second sentence is supported by evidence record E3 (the org's public engineering blog, approved). The model never saw v17's text.

**Not answerable from identifiers:** "Do you have at least five years of professional Python experience? Explain." Private `years_python=7`. With option A the model cannot answer truthfully; a fabricated "Yes, I have extensive experience" is exactly the invention §9 forbids. With option B, `years_python_gte_5: true` is in the descriptor, so the candidate is `"Yes — {{years_python_band}} years, primarily {{v22}}."` and the deterministic check confirms every emitted `{{}}` is authorized. If the user had *not* declared that derived fact, the result is:

```json
{"question_id": "q7", "status": "needs_information",
 "gap": {"kind": "hidden_value_reasoning",
         "variable_ids": ["years_python"],
         "needed": "comparison against threshold 5",
         "suggestion": "declare derived fact years_python_gte_5 or answer manually"}}
```

Failure behavior is a *record*, not a retry: rephrasing cannot fix it, so it consumes no regeneration budget.

Derived facts are computed by a tiny whitelist of pure functions (`gte`, `lte`, `band`, `nonempty`, `count`) declared in the variable definition — no expressions, no eval (§8 "templates are data").

---

## Q7. State and persistence integration

### Options

**A. LangGraph `SqliteSaver` checkpointer (thread = form session) + application repository in the same SQLite file.** Native durability for a mid-run crash inside one event; app tables hold everything cross-thread.
- Adds `langgraph-checkpoint-sqlite`. Checkpoints serialize graph state — so state must be designed to hold *references and bounded working context only* (PRD §6), and private bindings/credentials must be injected via `config["configurable"]`, which is not checkpointed.

**B. No LangGraph checkpointer; the repository is the only durable state.** Each event runs the graph to completion; Persist writes; state is rebuilt from tables on the next event. Simpler, one fewer dependency, but a crash between Generate (paid) and Persist loses the paid output unless Generate itself writes-through — which is what the Lab's durability principle says to do anyway.

**C. `MemorySaver` + repository.** Only useful for tests.

### Recommendation: **A**, but with write-through so the checkpointer is belt, not braces

- **Session identity:** `thread_id = form_session_id`; `scope_id` is carried in `configurable` and every repository query is scoped by it.
- **Re-entry:** every event is a fresh `graph.invoke(event, config={"configurable": {"thread_id": session_id, "scope_id": ..., "repo": repo, "provider": provider, "bindings": bindings}})`. The graph's first node (`route`) loads durable session state from the repository, *not* from the checkpoint; the checkpoint only matters for resuming an interrupted event.
- **Invalidation:** `update_form` computes a new `form_revision` (hash of questions+constraints+hints); candidates store the revision they were generated against; `get_candidate` returns `stale_context` if revisions differ. Source-version changes invalidate via `evidence.version` recorded on the candidate.
- **Event dedup:** `event(event_id PRIMARY KEY, session_id, type, applied_at, result_json)`. An already-applied `event_id` returns the stored result without re-running anything (exactly-once for feedback and ledger effects; replay-safe for candidates).
- **Concurrency:** optimistic — the event carries `expected_revision`; if it does not match the session's current revision the result is `stale_context` and nothing is written. Writes for one event happen in one `BEGIN IMMEDIATE` transaction; SQLite serializes writers per file.
- **Crash recovery / paid-call ledger:** `usage_ledger(call_id, event_id, role, state ∈ {reserved, confirmed, uncertain}, est_in, est_out, actual_in, actual_out)`. Reserve *before* the request; on response confirm with provider-reported usage; on exception after send (timeout, connection reset) mark `uncertain` — never zero (§11). On re-entry, an event with an `uncertain` row is **not** automatically retried: the result is `failed` with `retry_policy: manual` unless the event was submitted with `allow_retry_uncertain: true`, in which case one retry is permitted and both ledger rows remain. Provider adapters set an idempotency key where the provider supports it.
- **Generate writes through:** each question's candidates are written to `candidate` rows as soon as its structured response parses, before Evaluate runs (status `unevaluated`). A crash in Evaluate leaves paid work on disk; Evaluate is idempotent on `candidate_id`.

Checkpoint hygiene: state contains `variable_catalog` (descriptors only), never `bindings`; a test asserts the serialized checkpoint contains no binding value and no credential.

---

## Q8. Candidate promotion and retention

### Options

**A. Explicit approval only.** A candidate becomes a reusable `template` only on `record_feedback(outcome=approved)`.

**B. Selection + separate reuse permission.** `selected` caches it for the session and marks it "used once"; a second flag (`reuse_ok`) from the app promotes it.

**C. Auto-promote after N selections.** Convenient; violates "unselected/selected candidates must not automatically become approved knowledge".

### Recommendation: **A** (B is A with a second word for the same signal)

| Record | Retrieval as answer | Evidence for future claims | Deterministic autofill | Expiry |
|---|---|---|---|---|
| Candidate, valid, unseen | No | No | No | 30 days or form-revision change |
| Candidate, shown/selected | Same session only (as "previously shown") | No | No | 30 days after session close |
| Candidate, rejected | No | No | No | 30 days (diagnostic only) |
| Candidate, invalid | No | No | No | 7 days (diagnostic only) |
| Template, approved | Yes | **No** — a template is an answer, never evidence (§9: generated text does not support generated text) | Yes (the app may bind it to a question intent) | Until user revokes or source evidence is revoked |
| Evidence record | No (it is input, not an answer) | Yes | No | Until revoked |

Promotion writes a `template` row that *links back* to the candidate and its evidence refs, snapshots the context assignments as `applies`, and indexes it. Nothing generated ever gets `evidence` status; that boundary is structural (different table), not a flag.

---

## Q9. Operational defaults — SUPERSEDED (one validated `config.yaml`; values below are the starting defaults)

Ship conservative fixed defaults; expose **six** controls via a `Config` dataclass (env or YAML); everything else is a constant with a comment.

| Control | Default | Exposed? |
|---|---|---|
| `max_questions_per_batch` | 10 | yes |
| `initial_variants` | 2 (standard, concise) | no (PRD-fixed) |
| `max_regen_candidates` | 5 | no (PRD-fixed) |
| `retrieval_top_k` | 8 records/question | no |
| `max_context_tokens_per_question` | 1500 | no |
| `max_output_tokens_per_call` | 600 × questions in call, cap 4000 | no |
| `max_paid_calls_per_operation` | 3 (generate, optional eval, one retry) | no |
| `max_session_cost_usd` | 0.50 | yes |
| `max_session_tokens` | 150 000 | yes |
| `transient_retries` | 1, 2 s backoff | no |
| `needs_feedback_after` | 2 regeneration rounds without a selection (≤ 12 candidates) | yes |
| `learning_enabled` | true | yes |
| `evaluator_enabled` | true (conditional per Q5) | yes |

Pricing table for the cost guard: a static `pricing.yaml` keyed by model id, checked in, with the PRD's caveat that it is a guard, not a bill. Unknown model id → cost guard uses tokens only and warns.

---

## Q10. Existing-data ingestion

### Options

**A. Repository API only.** `repo.add_template(...)`, `repo.add_evidence(...)`, `repo.add_dimension(...)`. Callers (the app, a script) build records.

**B. A + a JSONL import helper.** `python -m answer_cache_agent.ingest records.jsonl --scope s1` reads one record per line, validates against a Pydantic model, writes through the repository, and embeds/indexes in the same transaction.

### Recommendation: **B**; refuse anything that smells like document management

Record format (one Pydantic union, discriminated on `kind`):

```jsonl
{"kind":"dimension","id":"role_family","label":"Role family"}
{"kind":"value","id":"agent_engineering","dimension_id":"role_family","label":"Agent engineering"}
{"kind":"evidence","id":"E3","locator":"https://example.org/eng-blog/evals","version":"2026-08-01","scope_id":"s1",
 "excerpt":"We ship evaluation tooling with every agent.","disclosure":"model_visible","approved_by":"user","approved_at":"2026-09-01"}
{"kind":"template","id":"T_B","intent":"motivation_for_organization","body":"{{v17}} I'm drawn to teams that ship evaluation tooling alongside agents.",
 "variables":["v17"],"evidence":["E3"],"context":[{"dimension":"role_family","value":"agent_engineering","mode":"applies"}],
 "status":"approved","approved_by":"user","approved_at":"2026-09-01","disclosure":"model_visible"}
{"kind":"variable","id":"v17","safe_description":"User-approved motivation statement for agent-engineering roles","value_type":"text",
 "permitted_use":"verbatim","derived_facts":[]}
```

Rules: `approved_by`/`approved_at` are required on `template` and `evidence` or the record is rejected (no "import as approved by default"); `disclosure` is required and defaults to nothing; variable *bindings* are never in this file (they live in the app's private store and reach the agent only at runtime). Index update is per record, inside the same transaction as the insert, tagged with the current `embedding_model`. Re-importing an existing id with a different body bumps `version` and re-embeds; identical body is a no-op.

Not included: PDF/DOCX parsing, chunking, web fetching. If evidence is long, the app supplies the approved excerpt.

---

## Blocking vs. tunable

**Blocking (settle before schema/graph code):**

| # | Decision | Recommended |
|---|---|---|
| Q1 | Metamodel shape and `applies`/`requires` modes | Flat + modes |
| Q3 | Vector store + embedder | sqlite-vec + fastembed local ONNX, protocols for both |
| Q4 | Ranking *structure* (filters → components → capped linear; joint→single→global back-off) | As specified |
| Q5 | Acceptance gate and whether an evaluator call exists | Conditional evaluator, gate as specified |
| Q6 | Derived-facts mechanism vs. descriptors-only | Derived facts + `needs_information` |
| Q7 | Checkpointer choice, ledger states, dedup key, concurrency rule | SqliteSaver + write-through, optimistic revision |
| Q8 | "Generated is never evidence" as a structural boundary | Separate tables |

**Tunable (ship a value, change later without restructuring):** Q2 hint precedence order and whether model suggestions are emitted at all; Q4 weights, `ALPHA/BETA/MIN_N/HALF_LIFE`; Q5 evaluator trigger conditions and 0.7 threshold; Q8 expiry windows; all of Q9; Q10 record fields beyond the required ones.

**Explicitly deferred:** value hierarchy (Q1-C), model-suggested hints affecting ranking (Q2-C), provider embeddings, encryption-at-rest of the SQLite file (the PRD asks for the threat model to be reviewed — recommendation: document that the file inherits OS user permissions and leave encryption to the surrounding app, which already owns the private bindings).

---

## What happens next

Once the owner marks each blocking row as accepted or changed, the implementation plan follows directly: repository + schema (Q1, Q3, Q7, Q8, Q10), then the four nodes with the event router (Q2, Q5, Q6), then ranking (Q4), then the harness, fixtures, and the §13 acceptance scenarios. The build record will state that the Foundry composer was not used and that Lab examples `langgraph/06_durable_agent_ops_workflow`, `langgraph/04_agent_docs_rag_graph`, and `shared/fanout_policy.py` were the reference patterns.
