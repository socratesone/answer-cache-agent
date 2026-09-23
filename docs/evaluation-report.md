# Evaluation Report

_Generated 2026-09-22 by `scripts/evaluate.py`. Embedder: HashEmbedder (lexical, offline); provider: scripted demo model (no network). Fixtures are synthetic (`fixtures/`). Ranking policy version 1._

## personal_application

### Retrieval relevance and contextual ranking

- Raw semantic hit@1 (intent): **6/6**; hit@3: **6/6**
- Correct top template after `requires` filter + context ranking: **6/6**

| Query | Context | Raw top | Ranked top | Expected |
|---|---|---|---|---|
| Why are you interested in this role? | `{"role_family": ["agent_engineering"], "sector": ["education"]}` | T_motivation_ae_edu_alt | T_motivation_ae_edu_alt | T_motivation_ae_edu / T_motivation_ae_edu_alt |
| Why do you want to work here? | `{"role_family": ["full_stack"]}` | T_motivation_ae_edu | T_motivation_fullstack | T_motivation_fullstack |
| What draws you to this position? | `{"role_family": ["agent_engineering"]}` | T_motivation_fullstack | T_motivation_ae_edu_alt | T_motivation_ae_edu / T_motivation_ae_edu_alt |
| Would you consider moving for this role? | `{}` | T_relocate | T_relocate | T_relocate |
| Describe your strongest technical skill. | `{"role_family": ["full_stack"]}` | T_strength_eval | T_strength_fullstack | T_strength_fullstack |
| What is your greatest strength? | `{"role_family": ["agent_engineering"], "sector": ["education"]}` | T_strength_eval | T_strength_eval | T_strength_eval |

### Feedback-adjusted ranking vs fixed baseline

- Query `Why are you interested in this role?` in context `{"role_family": ["agent_engineering"], "sector": ["education"]}`; runner-up `T_motivation_ae_edu` selected 5×.
- Baseline order: `['T_motivation_ae_edu_alt', 'T_motivation_ae_edu', 'T_motivation_fullstack', 'T_relocate']`
- Learning on: `['T_motivation_ae_edu', 'T_motivation_ae_edu_alt', 'T_motivation_fullstack', 'T_relocate']` → rose in context: **True** (preference component 0.857 at key `agent_engineering|education`; target score 0.803 → 0.857 vs leader 0.825; maximum preference shift is bounded at 0.075)
- Learning off (fixed baseline, same events recorded): `['T_motivation_ae_edu_alt', 'T_motivation_ae_edu', 'T_motivation_fullstack', 'T_relocate']` → unchanged: **True**
- Unrelated context `{"role_family": ["full_stack"], "sector": ["general"]}`: `['T_motivation_fullstack', 'T_motivation_ae_edu_alt', 'T_motivation_ae_edu', 'T_relocate']` → identical with learning on and off (no spill-over): **True**

### Scenario run (fixture events, scripted provider)

- Statuses per event: `['ready', 'partial', 'ready', 'ready', 'ready', 'ready', 'ready', 'ready', 'ready', 'ready']`
- Candidates by status: `{'valid': 9}`; valid candidates with no evidence/template reference: **0**
- Validation problems (constraint compliance after substitution): `[]`
- Abstentions / unresolved by reason: `{'insufficient_evidence': 1}`
- Paid calls (cumulative) after each event: `[('prepare_form', 0), ('generate_initial', 3), ('record_feedback', 3), ('record_feedback', 3), ('get_candidate', 3), ('get_candidate', 3), ('record_feedback', 3), ('record_feedback', 3), ('regenerate_question', 4), ('record_feedback', 4)]`
- `get_candidate` served from cache without a call: **2**; pre-generated valid candidates never shown: **6**
- Session usage: `{'calls': 4, 'tokens': 600, 'cost_usd': 0.0, 'uncertain': 0}`

## org_questionnaire

### Retrieval relevance and contextual ranking

- Raw semantic hit@1 (intent): **6/6**; hit@3: **6/6**
- Correct top template after `requires` filter + context ranking: **6/6**

| Query | Context | Raw top | Ranked top | Expected |
|---|---|---|---|---|
| Is customer data encrypted at rest and in transit? | `{"customer_tier": ["enterprise"], "region": ["eu"]}` | T_encryption | T_encryption | T_encryption |
| How quickly are customers notified of a security incident? | `{"customer_tier": ["enterprise"]}` | T_incident_enterprise | T_incident_enterprise | T_incident_enterprise |
| How quickly are customers notified of a security incident? | `{"customer_tier": ["smb"]}` | T_incident_enterprise | T_incident_smb | T_incident_smb |
| List your subprocessors and processing locations. | `{"region": ["eu"]}` | T_subprocessors_eu | T_subprocessors_eu | T_subprocessors_eu |
| What are your recovery objectives? | `{}` | T_dr | T_dr | T_dr |
| Do you hold any security certifications or attestations? | `{"customer_tier": ["smb"]}` | T_soc2 | T_soc2 | T_soc2 |

### Feedback-adjusted ranking vs fixed baseline

- Query `How quickly are customers notified of a security incident?` in context `{"customer_tier": ["enterprise"]}`; runner-up `T_incident_smb` selected 5×.
- Baseline order: `['T_incident_enterprise', 'T_incident_smb', 'T_soc2', 'T_dr', 'T_encryption']`
- Learning on: `['T_incident_enterprise', 'T_incident_smb', 'T_soc2', 'T_dr', 'T_encryption']` → rose in context: **False** (preference component 0.857 at key `enterprise`; target score 0.570 → 0.624 vs leader 0.825; maximum preference shift is bounded at 0.075)
- Learning off (fixed baseline, same events recorded): `['T_incident_enterprise', 'T_incident_smb', 'T_soc2', 'T_dr', 'T_encryption']` → unchanged: **True**
- Unrelated context `{"customer_tier": ["smb"]}`: `['T_incident_smb', 'T_incident_enterprise', 'T_soc2', 'T_dr', 'T_encryption']` → identical with learning on and off (no spill-over): **True**

### Scenario run (fixture events, scripted provider)

- Statuses per event: `['ready', 'ready', 'ready', 'ready', 'ready', 'partial']`
- Candidates by status: `{'valid': 8, 'invalid': 2}`; valid candidates with no evidence/template reference: **0**
- Validation problems (constraint compliance after substitution): `['length 145 > 80', 'length 145 > 80']`
- Abstentions / unresolved by reason: `{}`
- Paid calls (cumulative) after each event: `[('prepare_form', 0), ('generate_initial', 5), ('record_feedback', 5), ('record_feedback', 5), ('get_candidate', 5), ('get_candidate', 5)]`
- `get_candidate` served from cache without a call: **1**; pre-generated valid candidates never shown: **6**
- Session usage: `{'calls': 5, 'tokens': 750, 'cost_usd': 0.0, 'uncertain': 0}`

## Reading this report

- The scripted provider always cites the top-ranked bundle item and never invents, so *supported vs unsupported* here measures the deterministic evidence-linkage gate, not a real model's honesty. Run with real providers to measure that.
- Abstention on the unsupported question is driven by retrieval returning nothing above `retrieval.min_similarity`; with the real embedder unrelated questions still score ~0.5–0.6, so abstention there depends on the generator (documented limitation, Q5/Q6).
- Learning is bounded: the preference component's weight is capped by config; the report shows it moving a runner-up, not overriding filters. 'Rose in context' with 'no spill-over' is the specified behavior, not a claim of generalized improvement.
- Numbers are on a six-case synthetic set per domain. Benchmark size and numerical targets remain a review item (PRD §13).
