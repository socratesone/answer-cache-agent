# Interface → Fable integration handoff

Ownership: all interface work is under `interface/`. Engine, root files, schemas, scripts, fixtures and existing docs are read-only. Baseline: CODEX.md, engine 0.1. No engine contract changes are made by this application.

| PRD action | Existing contract | Remaining gap / user impact | Acceptance required from engine |
|---|---|---|---|
| Activate / change context | prepare_form / update_form | Supported; browser owns extraction | No paid calls; revision invalidates prior candidates |
| Cached AI help / concise | get_candidate | Supported | Cache miss never generates |
| Batch / new alternatives | generate_initial / regenerate_question | Supported | Explicit scope; engine limits; uncertain calls not retried |
| Shown / selected / edited / rejected / approved | record_feedback | Supported; edit payload must remain symbolic | Exact observations only; approval is not factual evidence |
| Create saved template / descriptor / category | ingest records + Repository | Supported through importer; no direct table access | Preserve approval/disclosure and indexing |
| Render / private values | rendering helpers + RuntimeDeps.bindings | Host-owned protected store | Values absent from events, checkpoints and provider requests |
| Find saved answers | Repository.search/template + requires_satisfied | No public complete eligibility/ranked saved lookup (especially local_only); search is only top-k neighbours | Service returns eligible approved matches, reasons and disclosure without paid calls |
| Automatic exact-match fill | Browser-owned decision | Missing complete alias lookup / unique eligible-match service; disabled, never infer uniqueness from top-k | Duplicate eligible aliases block autofill; revocation/context respected |
| Library and category browsing | variables() exists; template(id) exists | Missing enumeration/pagination for templates, intents/aliases, dimensions, values and cross-session candidates | List all scoped records without direct SQL |
| Template editing | add_template/import upserts | No atomic full edit with aliases/context/index invalidation; create supported, full edit gated | Atomic edit, reindex aliases and invalidate affected caches |
| Remember wording | add_intent_alias | Scope-wide intent alias only; no context-specific association or alias removal/reindex service | Explicit association scope; atomic reindex; no universal accidental mapping |
| Variable rename/delete | add_variable / variables | Missing references and atomic rename/delete; values can be updated locally | References surfaced; no orphan placeholders; invalidate affected candidates |
| Category delete | add_dimension/add_value | Missing reference checks and deletion | Referenced assignments protected |
| Backup / restore / export / delete data | No complete public service | Controls unavailable; no direct database copying while active | Consistent snapshot, validated restore, credential exclusion and explicit private-value export |
| Provider configuration | Credentials / ModelRoles / Config | No supported-model catalogue/default-role source; pricing is not a catalogue | Authoritative provider→models/default roles; live normalization tests |
| Spending | Result.usage + budget config | Missing per-call cost-known flag; cost_usd can conceal null costs | Unknown cost distinguishable from known zero; estimates labeled |
| Stop / progress | Bounded handle_event only | Host cancels queued work and suppresses insertion, cannot interrupt active generation | Cooperative cancellation between paid calls and operation status reconciliation |
| Change bindings/config/templates | Runtime deps and repository writes | No public affected-cache invalidation service | Cached validity reflects dependency changes, not just form revision |
| Installer / browser transport | Assigned to interface by CODEX.md | Windows release validation required | No engine changes requested |

Release blockers: authoritative exact-match autofill, complete management, safe invalidation and portability are not represented as finished. UI uses explicit unavailable states. Native Windows installation, signing, store approval, live providers and publication require independent evidence.

Privacy clarification: raw captured answers are never event fields. Save as a local-only template, or consciously author model-visible symbolic text. Free-text feedback/question context is model-eligible and must pass host leak checks. Known-value matching cannot guarantee anonymity.
