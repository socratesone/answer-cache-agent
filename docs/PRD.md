# Product Requirements Document

## Questionnaire Completion Agent

**Version:** 0.1
**Status:** v0.1 built; the open design questions below are decided in `design-review.md`
**Implementation:** Python and LangGraph
**Intended repository license:** MIT (Massachusetts Institute of Technology)

> **Stop answering the same questions from scratch.**

## 1. Purpose

Build a reusable LangGraph agent that produces grounded, context-appropriate answer templates for questionnaires. The agent retrieves relevant information from a local knowledge collection, generates candidate templates, evaluates them, and records outcomes that inform future retrieval and selection.

The project has two objectives:

* **Practical utility:** Help users complete repetitive forms without repeatedly composing the same answers.
* **Technical demonstration:** Provide an inspectable, working example of context engineering, semantic retrieval, evaluation, bounded retries, privacy-conscious generation, telemetry, and feedback-driven improvement.

The demonstration must include these capabilities in the first release. Replacing semantic retrieval with string matching, or deferring evaluation and learning to a later version, would not satisfy the project's purpose.

### Decision status

**Confirmed** means established during the design discussion. **Proposed** means a concrete draft requirement supplied for review. **Open** means the reviewing agent must develop alternatives for the owner to select.

The document specifies the agent, not the complete surrounding application.

---

## 2. Scope and system boundary

### In scope

The deliverable is a Python package containing the LangGraph workflow, its state and event contracts, retrieval and persistence components, prompt definitions, model-provider adapters, evaluation logic, telemetry, and tests.

The agent must be usable independently of a browser through a small test harness.

### Outside this document's implementation scope

The Chrome extension, page extraction, deterministic autofill interface, native application installer, local web server, configuration screens, landing page, and release-distribution process are outside scope.

They are integration partners, not components this document requires the agent to build.

The agent does not submit forms, operate websites, or decide whether to overwrite user-entered text.

### Expected environment

The surrounding application will run locally. It will provide structured form context and access to local data. The Python agent will make authorized model requests directly to the user's selected provider using the user's credentials.

There is no required centrally hosted application service, model-call proxy, or hosted vector database.

### Responsibility boundary

| Surrounding application                                                     | Agent                                                                      |
| --------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Extract questions, field constraints, and relevant page context.            | Validate and organize received context.                                    |
| Perform deterministic autofill and manual answer lookup.                    | Retrieve additional relevant context using semantic search.                |
| Report which fields already contain answers and their template references.  | Generate and evaluate candidate answer templates.                          |
| Supply user-defined contextual hints and user-interaction events.           | Use those hints and events in retrieval and ranking.                       |
| Display answers and obtain user feedback.                                   | Persist candidates, evaluation results, and feedback-derived ranking data. |
| Maintain private variable values and render approved substitutions locally. | Reference authorized variables without transmitting their private values.  |

The final module boundary for local template rendering remains open. Its privacy and validation requirements do not.

---

## 3. Confirmed product decisions

| Area                     | Decision                                                                                                                        |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Framework                | A Python LangGraph agent. No Python-to-JavaScript translation is required.                                                    |
| Architecture             | Four logical processing nodes: **Prepare/Retrieve, Generate, Evaluate, Persist/Learn**.                                         |
| Invocation               | One stateful system accepts different interaction events and follows different paths. Every event does not traverse every node. |
| Initial form preparation | Establishing form context makes **zero generative model calls and zero paid external model requests**.                          |
| Generation authorization | Generation occurs only in response to an explicit user request, within that request's authorized scope and budget.              |
| Initial candidates       | Request **two candidates per eligible question**: a standard answer and a more concise alternative.                              |
| Subsequent generation    | A targeted regeneration request produces **at most five candidates** for the requested question.                                |
| Reuse                    | Previously generated, still-valid alternatives can be returned without another model call.                                      |
| Retrieval                | Semantic retrieval is part of the agent, not a required upstream service.                                                       |
| Templates                | Generated answers use symbolic references to user-defined variables. Private variable values remain local.                      |
| Persistence              | SQLite is the local application-data store. The vector-index implementation remains open.                                       |
| Providers                | Initial provider support is OpenAI and Anthropic, behind replaceable adapters.                                                  |
| Model selection          | Two configurable model roles: a routine model and a more capable model for harder work.                                         |
| Domain model             | Context categories are user-defined. Job titles, industries, company sizes, and similar concepts must not be hard-coded.        |
| Learning                 | Evaluation and observed user feedback influence future ranking. Neither replaces explicit applicability or privacy rules.       |

Candidate limits are ceilings, not instructions to fabricate answers. A question with insufficient support may produce no usable candidates and an explicit request for missing information.

---

## 4. Interaction and execution model

The agent operates through bounded invocations associated with a persistent form session. It does not need to remain actively executing while a person reads or edits a form.

### Proposed event contract

Names below are illustrative; the behavior is required.

| Event                 | Expected behavior                                                                                                                 | New model generation? |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| `prepare_form`        | Establish or update form context, references, constraints, and contextual hints. Persist session state.                           | No                    |
| `generate_initial`    | Retrieve or reuse valid retrieval results; generate the initial two-candidate set for eligible questions in the authorized batch. | Yes, when uncached    |
| `get_candidate`       | Return a valid cached candidate or alternate for a specified question.                                                            | No                    |
| `regenerate_question` | Use the current context and feedback to generate up to five new candidates for one question.                                      | Yes                   |
| `record_feedback`     | Record exposure, selection, editing, rejection, or approval; update applicable ranking data.                                      | No                    |
| `update_form`         | Apply changed questions, answers, constraints, or hints; invalidate affected context and candidates.                              | No                    |

A cache miss during `get_candidate` must not silently authorize a paid request.

### Initial batch behavior

The first generation request may prepare answers for other unanswered questions on the current form, not just the question whose help control was activated.

The request must identify:

* The field or fields the user is currently asking to populate.
* The additional questions authorized for candidate pre-generation.
* The spending and batch limits applicable to that request.

The agent returns the requested candidate for immediate use and stores the remaining candidates for later retrieval. It must distinguish **generated**, **returned**, and **actually shown** candidates.

Already populated fields are excluded unless explicitly targeted.

### Subsequent interactions

Requesting a concise answer should return the existing concise variant when it remains applicable. Requesting genuinely new candidates invokes the targeted-generation prompt.

Repeated rejection should eventually produce a structured `needs_feedback` result rather than an indefinite regeneration loop. The surrounding application can then ask what is wrong with the answers and submit the response as additional context.

The threshold and feedback-request format remain open.

### Context reuse

The agent may bypass retrieval preparation only when the stored context remains valid for the current question set, form revision, source versions, and contextual hints.

"Context was prepared previously" is not sufficient by itself.

---

## 5. Four-node graph

The ordinary generation path is:

```text
Prepare / Retrieve
        ↓
Generate
        ↓
Evaluate
        ↓
Persist / Learn
        ↓
Return result, request information, or take a bounded retry path
```

Routing, validation helpers, and provider adapters do not need to become additional agent personas or separate products.

### Node 1: Prepare / Retrieve

**Purpose:** Assemble the bounded, relevant, provider-safe context needed for the requested operation.

Responsibilities include validating session updates, identifying target questions, resolving existing template references, applying contextual hints, performing semantic retrieval, ranking eligible records, and selecting authorized variable descriptors.

This node must distinguish information already supplied by deterministic autofill from information retrieved by the agent.

Initialization must work without a generative model. Any model-assisted query reformulation must occur only inside an authorized generation operation and count against its budget.

**Output:** A per-question context bundle with provenance, selected template and evidence references, permitted variables, retrieval scores, and identified information gaps.

### Node 2: Generate

**Purpose:** Produce candidate templates under the selected prompt mode and model policy.

The initial mode requests a standard and concise candidate for each target question. The targeted mode incorporates current context, previously shown candidates, and available feedback.

Candidates must preserve required qualifications and factual meaning. "Concise" does not authorize removing an important exception or turning a qualified claim into an absolute one.

**Output:** Structured candidate records or explicit abstentions, linked to their questions and supporting context.

### Node 3: Evaluate

**Purpose:** Assess candidate validity and quality, and interpret explicitly reported user outcomes.

Evaluation includes structural validity, variable authorization, answer relevance, contextual applicability, factual support, and field constraints.

Three kinds of information must remain separate:

| Information               | Meaning                                                          |
| ------------------------- | ---------------------------------------------------------------- |
| Generator self-assessment | A claim made by the same model that generated the answer.        |
| Evaluation result         | Findings from deterministic checks or a configured evaluator.    |
| User feedback             | An interaction actually reported by the surrounding application. |

The evaluator must not invent selection, editing, or rejection events.

A separate evaluator model call is **not yet a settled requirement**. The evaluation node is required; the balance between deterministic validation, generator self-checks, and an additional semantic evaluator is an open design decision.

### Node 4: Persist / Learn

**Purpose:** Turn generated results and observed outcomes into durable, inspectable records.

Persist candidates, evidence references, evaluations, usage, and feedback. Apply bounded ranking updates under a versioned policy.

Valid but unselected candidates may remain available. Invalid candidates must not enter normal retrieval as usable answers; retain only the diagnostic material permitted by the retention policy.

Database writes must tolerate event replay without duplicating candidates, charging usage twice in the ledger, or applying the same feedback repeatedly.

---

## 6. State, inputs, and outputs

### Input contract

Each invocation needs a unique event identifier, a form-session identifier, a data-scope identifier, the event type, and the expected form-state revision.

The payload may contain structured questions and constraints, sanitized page context, pre-populated template references, contextual hints, requested candidate identifiers, or explicit feedback.

Repository access and provider credentials must be supplied through trusted runtime dependencies, not through model-visible page content.

### Proposed session-state structure

| State group           | Contents                                                                              |
| --------------------- | ------------------------------------------------------------------------------------- |
| Identity and revision | Session, scope, event, form revision, schema version.                                 |
| Form context          | Questions, constraints, existing answer references, sanitized contextual information. |
| Contextual hints      | Active dimension/value assignments and where they came from.                          |
| Retrieval state       | Per-question query context, retrieved references, score components, source versions.  |
| Variable catalog      | Authorized identifiers and safe descriptors, without private values.                  |
| Candidate state       | Candidate references, variants, validation results, display history, approval state.  |
| Feedback state        | Explicit outcomes and a bounded relevant feedback history.                            |
| Execution control     | Requested operation, prompt mode, model role, retries, stop conditions.               |
| Budget and usage      | Reserved and recorded usage, remaining limits, uncertain requests.                    |
| Result state          | Available answers, unresolved questions, failures, required next action.              |

Do not copy the complete knowledge collection into graph state. Keep bounded working context and references to durable records.

Private variable values and provider credentials must not be serialized into ordinary graph checkpoints.

### Session memory versus reusable memory

Form-session state and the cross-form knowledge collection are separate persistence concerns. LangGraph distinguishes thread-scoped checkpoints from application data retained across threads; the implementation should preserve that distinction rather than treating one session's state as the complete database. ([Docs by LangChain][1])

The exact checkpoint integration, state-update rules, and transaction boundaries require implementation review.

### Output contract

Return structured data containing the updated state revision, requested candidates, other cached-candidate references, evidence references, evaluation findings, usage, and unresolved information.

Proposed statuses include `ready`, `partial`, `needs_information`, `needs_feedback`, `budget_exhausted`, `stale_context`, and `failed`.

An abstention, a provider failure, and a budget stop must remain distinguishable.

---

## 7. Semantic retrieval and contextual metamodel

### Retrieval requirement

Retrieval must use the question **and its context**. Question similarity alone is insufficient.

For example, "Why do you want to work here?" may require different templates depending on the role, industry, or user's stated motivation. Those contextual distinctions must be represented as data rather than embedded in application-specific code.

Retrieval must operate over a bounded subset of a potentially large local collection. Sending the entire collection to a model is prohibited.

### Proposed metamodel

These are logical entities, not a requirement to create one physical table per row.

| Entity                    | Purpose                                                                                             |
| ------------------------- | --------------------------------------------------------------------------------------------------- |
| Question or intent record | Stores question wording, aliases, and optional relationships to recurring question intents.         |
| Context dimension         | A user-defined axis of distinction.                                                                 |
| Context value             | A user-defined value belonging to a dimension.                                                      |
| Context assignment        | Associates values with a form, question, or template, including assignment provenance.              |
| Template/candidate        | Stores symbolic answer text, versions, applicability, evidence links, and approval status.          |
| Variable definition       | Describes an available substitution and its permitted use, without exposing its private binding.    |
| Evidence record           | Identifies approved supporting material, its version, locator, scope, and validity information.     |
| Evaluation/feedback event | Records what was evaluated, shown, selected, edited, rejected, or approved in a particular context. |

**Proposed first-release representation:** Flat dimensions with user-defined values and many-to-many associations. No hierarchy or graph database is required by this draft.

Whether that representation is sufficient, and what cardinality rules it needs, remains an explicit review question.

### Concrete example

The following is illustrative data, not a built-in taxonomy:

```text
Dimension: role_family
Values: full_stack, agent_engineering

Dimension: sector
Values: education, general

Template A
Question intent: motivation_for_organization
Context associations: role_family = full_stack

Template B
Question intent: motivation_for_organization
Context associations: role_family = agent_engineering

Template C
Question intent: motivation_for_organization
Context associations: sector = education
```

For a form tagged `agent_engineering` and `education`, the system should consider B and C in the relevant context. It must not assume there is one universal winning template.

If the user repeatedly selects B for that context, its future ranking can increase there. That does not make B the preferred answer for unrelated full-stack applications.

### Ranking requirements

Apply access, approval, and explicit applicability restrictions before preference scoring.

Among eligible records, retain separate score components for semantic relevance, contextual match, evaluation quality, historical preference, and freshness where applicable.

The exact combination formula remains open. Required properties are:

* Popularity cannot override an explicit restriction or make unsupported content authoritative.
* Missing hints are unknown information, not automatic mismatches.
* Ranking must be inspectable: a developer can determine which components affected an ordering.

Embeddings must not be treated as anonymous data merely because they are numeric representations. The retrieval design must apply appropriate protection to the index as well as its source records. ([OWASP Cheat Sheet Series][2])

### Index maintenance

The implementation must support adding, updating, invalidating, and deleting indexed records. Record the embedding-model and index versions so changes do not silently mix incompatible representations.

The embedding implementation, vector-storage mechanism, and supported corpus-size target remain open. Local operation is required; a hosted indexing service is not.

---

## 8. Template variables and privacy boundary

### Required separation

The agent must distinguish:

| Data                            | Handling                                                             |
| ------------------------------- | -------------------------------------------------------------------- |
| Private variable binding        | Remains local; never included in outbound model requests.            |
| Safe variable descriptor        | May be sent when authorized and relevant.                            |
| Template body                   | May be sent only if its fixed text is also permitted for disclosure. |
| Approved evidence excerpt       | May be sent only within its scope and disclosure rules.              |
| Unknown or unclassified content | Must not be assumed safe merely because it appeared on a webpage.    |

A variable may represent a short value or several sentences.

### Illustrative model-visible descriptor

```text
variable_id: v17
safe_description: User-approved motivation statement for this context
value_type: text
permitted_use: verbatim insertion
```

The model may emit `{{v17}}`. Local code resolves the binding afterward.

The exact placeholder syntax is proposed, not finalized.

### Required limitations

**An opaque identifier alone does not provide usable meaning.** The model needs an authorized description or other safe context to select a variable appropriately.

**A model cannot evaluate information it has not received.** If a question requires comparing, summarizing, or reasoning about hidden values, the agent must obtain an authorized local result or return a request for information. It must not pretend that naming a variable reveals its contents.

**Substitution is not complete anonymization.** Question text, descriptors, surrounding prose, and feedback can themselves reveal sensitive information. Disclosure control must cover the complete outbound payload, not just known variable bindings.

### Validation and rendering requirements

Only variables authorized for the current question and scope may appear in a candidate. Unknown or disallowed references must be rejected.

Templates must be treated as data, not executable expressions. The renderer must not execute generated code or arbitrary template functions.

Final length and format checks must occur after local substitution. A short template containing a long private value may still exceed a form's limit.

Provider-safe context construction must cover generation, evaluation, query reformulation, remote embeddings if ever introduced, and telemetry exports.

Prompt instructions are not a sufficient security boundary against malicious page text or retrieved content. Validate inputs and outputs and restrict the operations available to the model independently of what the prompt says. ([OWASP Cheat Sheet Series][3])

---

## 9. Candidate generation and evaluation contracts

### Candidate record

Each candidate must identify its question, generation batch, variant, template text, referenced variables, and supporting evidence or approved-template references.

Store the prompt version, model identifier, relevant context revision, validation status, and any missing-information flags.

Use a machine-validated structured response, such as JSON (JavaScript Object Notation), rather than extracting answers from loosely formatted prose.

Schema compliance does not establish factual correctness. OpenAI's structured-output documentation explicitly notes that schema-conforming responses can still contain mistakes. Structural validation and semantic assessment must therefore remain separate. ([OpenAI Developers][4])

### Grounding rules

Answers must not invent experience, qualifications, organizational practices, commercial commitments, or personal motivations.

Claims must be traceable to approved evidence, approved user statements, or authorized variable semantics. Retrieved content that conflicts or lacks current applicability must produce an explicit limitation rather than a confident synthesis.

A generated candidate is not an independent source supporting another generated candidate.

The agent must distinguish **insufficient evidence** from **poor wording**. Rephrasing cannot repair missing factual support.

### Evaluation behavior

Deterministic checks must cover record shape, candidate counts, variable validity, question association, scope, and enforceable field constraints.

Semantic evaluation must address relevance, factual support, contextual fit, completeness, and preservation of important qualifications.

Self-assessment may provide useful diagnostic signals, but must not be labeled independent verification.

Provider refusal, truncated output, malformed output, and unsupported schema behavior require explicit handling. Anthropic documents refusal and token-limit cases that can interrupt otherwise structured output; adapters must normalize such outcomes without treating them as successful candidate sets. ([Claude Platform][5])

---

## 10. Persistence, feedback, and improvement

### Candidate lifecycle

Store validation status, user approval, and interaction history separately.

A candidate can be structurally valid but unseen, selected for one form but not approved for future reuse, or rejected in one context without being globally unsuitable.

Unselected candidates may be cached. They must not automatically become approved knowledge or evidence.

The rule for promoting a candidate into the reusable approved-template collection remains open.

### Feedback telemetry

Record which candidates were actually shown, their display order, the alternatives available, and the relevant context snapshot.

Distinguish selection, explicit rejection, editing, and approval. Merely generating a candidate does not constitute exposure. Leaving a candidate unused does not establish rejection.

Requesting another answer does not prove that every hidden candidate was rejected.

### Concrete learning behavior

For a template in a particular question/context combination, maintain observed exposure and outcome statistics.

A user selection may increase preference within that context. An explicit rejection may decrease it. An edit may indicate that the template was useful but needed modification; do not automatically interpret editing as either full acceptance or total failure.

The first release must implement configurable ranking updates, not just collect events for a hypothetical future learning system.

### Required controls

Learning must be disableable while telemetry remains available. Ranking updates must be reproducible from recorded events, bounded in effect, and attributable to a policy version.

Keep evaluation quality and user preference separate. A popular answer may still be unsupported; a factually supported answer may still be poorly suited to the user's preferred wording.

Sparse-data behavior, time decay, smoothing, and treatment of overlapping context dimensions remain open.

No model retraining or autonomous rewriting of system prompts is required.

---

## 11. Models, prompts, and spending controls

### Model roles

| Role     | Intended use                                                                          |
| -------- | ------------------------------------------------------------------------------------- |
| Routine  | Normal generation and other lower-complexity model tasks.                             |
| Advanced | Harder evaluation or regeneration when an explicit routing policy permits escalation. |

The owner must be able to configure the model assigned to each role. Provider-specific request handling must remain inside adapters.

Do not hard-code a moving "frontier" model designation. The exact escalation conditions and whether both roles may use the same model are review decisions.

### Prompt modes

Maintain separate, versioned prompt definitions for initial batch generation and targeted regeneration.

An evaluator prompt is required if the selected evaluation architecture uses a model. Query-reformulation prompts are required only if that capability is selected.

Prompt selection must follow the requested operation and validated state, not instructions embedded in form content.

### Budget requirements

Check limits before every paid request, including evaluation, retries, and adapter-level retries.

Limits must cover candidate counts, questions per batch, input and output tokens, paid calls per operation, cumulative form-session usage, and retry attempts.

Record estimated and provider-reported usage separately. Unknown usage after an interrupted request must not be recorded as zero.

Cached-answer retrieval, ordinary feedback persistence, and initial form preparation must not trigger paid calls.

Evaluate batch efficiency using total usage and candidate reuse, not call count alone. Pre-generating unused alternatives must remain visible in telemetry.

Exact defaults remain open. The application budget is a guard based on available usage and pricing information, not a guarantee about the provider's final bill.

---

## 12. Reliability and security requirements

### State integrity

Every result must identify the form revision it was generated against. Stale results must not silently replace answers after the form or its context changes.

Duplicate events must not duplicate feedback effects or candidate records. Concurrent actions on the same session need a defined serialization or revision-conflict policy.

Source, template, variable-binding, and permission changes must invalidate affected cached results before reuse.

### Failure behavior

Missing context, retrieval failure, conflicting evidence, provider failure, budget exhaustion, and persistence failure must produce distinguishable outcomes.

Preserve completed work from a partially successful batch. Do not regenerate successful questions merely because another question failed.

Do not fall back to unsupported model knowledge when retrieval fails.

A request with an uncertain provider outcome requires recorded uncertainty and an explicit retry policy; crash recovery must not blindly repeat paid operations.

### Security boundary

Provider credentials must stay out of page payloads, generated templates, graph checkpoints, and logs. Retrieve credentials through a trusted local runtime interface.

Enforce data-scope boundaries in retrieval, caches, rendering, and persistence. Treat webpage content, retrieved text, and model output as untrusted data.

Use local telemetry by default, with no external tracing dependency. Provide deletion and retention behavior covering candidates, indexes, and derived records.

Local execution does not remove the need for credential protection, safe rendering, or access controls. The precise local threat model and encryption responsibilities require review; this draft makes no "zero privacy risk" claim.

---

## 13. Acceptance tests and deliverables

### Required acceptance scenarios

| Scenario                         | Required result                                                                                           |
| -------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Prepare a form                   | Persistent context is established with no paid model request.                                             |
| Initial generation               | Two variants are requested per eligible question; only requested fields are designated for immediate use. |
| Cached concise alternative       | Returned without a new model call.                                                                        |
| Targeted regeneration            | No more than five candidates; relevant feedback influences the request.                                   |
| Paraphrased question             | Semantic retrieval finds applicable records without an exact string match.                                |
| Same question, different context | Contextual hints can change the ranking of eligible templates.                                            |
| Hidden candidate                 | No rejection is inferred from lack of selection.                                                          |
| Duplicate feedback event         | Ranking is updated once.                                                                                  |
| Missing or conflicting evidence  | Unsupported assertions are withheld and the gap is reported.                                              |
| Protected variable               | Private values are absent from captured outbound payloads and ordinary telemetry.                         |
| Unauthorized variable reference  | Candidate is blocked before local rendering.                                                              |
| Overlong resolved answer         | Constraint failure is detected after substitution.                                                        |
| Stale form or source             | Affected cached candidates are not silently reused.                                                       |
| Budget exhaustion                | Further paid requests stop with an explicit status.                                                       |
| Restart and partial failure      | Durable work remains available without duplicating completed effects.                                     |

Use synthetic fixtures for public tests. Include both personal-application and organizational-questionnaire examples without hard-coding either domain into the implementation.

### Evaluation report

Report retrieval relevance, contextual ranking behavior, supported versus unsupported claims, correct abstention, constraint compliance, candidate reuse, and measured usage.

Compare feedback-adjusted ranking with a fixed baseline on a defined test set. Demonstrate that the learning mechanism behaves as specified; do not claim generalized improvement merely because ranking weights change.

Numerical targets and benchmark size require review.

### Build deliverables

Deliver the Python package, versioned schemas and prompts, local persistence/indexing components, provider adapters, a browser-independent demonstration harness, tests, and architecture documentation.

The documentation must explain the four nodes, event pathways, privacy boundary, ranking policy, and known limitations.

Include a build record identifying what was generated by tooling and what was written by hand. Do not claim a fully automated build unless that record supports it.

---

## 14. Open design questions for the reviewing agent

The reviewing agent must produce options for the following questions **before unresolved choices are treated as final requirements**.

The options listed here are comparison directions, not selections.

| Question                                 | Options to investigate                                                                                                         | Required decision output                                                                                                                                    |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Concrete metamodel**                | Flat dimensions and values; grouped tags; a limited hierarchy where demonstrably necessary.                                    | A small proposed schema with example records and explicit association/cardinality rules. Explain overlapping contexts without fixing a domain taxonomy.     |
| **2. Active contextual hints**           | Caller-supplied selections; user-maintained deterministic rules; model-suggested assignments during authorized generation.     | Explain how a form receives its hints, how uncertainty is represented, and whether users must confirm inferred assignments.                                 |
| **3. Semantic retrieval implementation** | SQLite-based vector search; a separate local index; direct local vector scoring for an explicitly bounded collection.          | Compare embedding choice, installation footprint, corpus limits, latency, licensing, updates, and index rebuilding.                                         |
| **4. Ranking and correlation updates**   | Smoothed contextual outcome counts; capped additive facet scores; joint-context statistics with fallback when data is sparse.  | Supply actual formulas or pseudocode. Show cold start, overlapping dimensions, rejection, edits, decay, and protection against global-popularity dominance. |
| **5. Evaluation architecture**           | Deterministic checks plus generator self-assessment; a separate semantic evaluator; conditional evaluator escalation.          | Explain what each can detect, what it cannot verify, and the additional cost. Identify the proposed acceptance gate.                                        |
| **6. Hidden-value reasoning**            | Approved safe descriptors; locally computed derived facts; explicit requests for information when hidden values are necessary. | Demonstrate a question answerable by substitution and one that cannot be answered safely from identifiers alone. Define the failure behavior.               |
| **7. State and persistence integration** | Alternative checkpoint, repository, and transaction arrangements compatible with the four-node design.                         | Define session identity, re-entry, invalidation, event deduplication, concurrent updates, and crash recovery.                                               |
| **8. Candidate promotion and retention** | Explicit approval for reusable memory; selection plus separate reuse permission; other clearly distinguished promotion rules.  | Explain what is cached, what can support future answers, what can drive deterministic autofill, and when unused records expire.                             |
| **9. Operational defaults**              | Conservative fixed defaults versus a small set of exposed controls.                                                            | Propose batch, retrieval, token, spending, retry, and feedback thresholds without requiring extensive user configuration.                                   |
| **10. Existing-data ingestion**          | Accept normalized records through repository interfaces; provide a minimal text/structured-data import helper.                 | Define the initial supported record format, approval metadata, and index-update behavior. Do not expand into a general document-management application.    |

### Review response format

For each question, return two or three viable options where meaningful, their implementation and maintenance implications, a recommendation with reasons, and a concrete example where the abstraction would otherwise remain unclear.

Clearly distinguish decisions that block implementation from defaults that can be tuned later.

The review must preserve the project's central constraint:

> **Build a small but complete LangGraph agent that demonstrates the intended engineering capabilities. Keep the surrounding application outside this scope; do not simplify the agent by removing the capabilities it exists to demonstrate.**

[1]: https://docs.langchain.com/oss/python/langgraph/persistence "Persistence - Docs by LangChain"
[2]: https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html "RAG Security - OWASP Cheat Sheet Series"
[3]: https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html "LLM Prompt Injection Prevention - OWASP Cheat Sheet Series"
[4]: https://developers.openai.com/api/docs/guides/structured-outputs "Structured model outputs | OpenAI API"
[5]: https://platform.claude.com/docs/en/build-with-claude/structured-outputs "Structured outputs - Claude Platform Docs"
