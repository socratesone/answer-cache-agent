"""Public contracts: inbound events, outbound results, and model-facing structured outputs.

These models are the integration boundary with the surrounding application. JSON Schema for
each is exported by `scripts/export_schemas.py` into `schemas/`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["prepare_form", "generate_initial", "get_candidate", "regenerate_question", "record_feedback", "update_form"]
Status = Literal["ready", "partial", "needs_information", "needs_feedback", "budget_exhausted", "stale_context", "failed"]
Variant = Literal["standard", "concise", "alternative"]
Outcome = Literal["shown", "selected", "rejected", "edited", "approved"]
HintSource = Literal["caller", "rule", "user"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- inbound ---------------------------------------------------------------------------------

class Constraints(_Strict):
    max_length: int | None = Field(default=None, ge=1)
    max_words: int | None = Field(default=None, ge=1)
    required: bool = False


class Question(_Strict):
    id: str
    text: str
    constraints: Constraints = Constraints()
    prefilled: bool = False
    prefilled_template_ref: str | None = None
    hints: list["Hint"] = []


class Hint(_Strict):
    dimension: str
    value: str
    source: HintSource = "caller"


class HintRule(_Strict):
    """User-maintained deterministic rule: regex over a page field assigns a value (Q2)."""
    id: str
    match_field: Literal["page_url", "page_title", "question_text"]
    pattern: str
    dimension: str
    value: str


class RequestLimits(_Strict):
    max_questions: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=0)


class PrepareFormPayload(_Strict):
    questions: list[Question]
    page_url: str | None = None
    page_title: str | None = None
    page_context: str | None = Field(default=None, description="Sanitized, disclosure-approved page text only.")
    hints: list[Hint] = []
    rules: list[HintRule] = []


class GenerateInitialPayload(_Strict):
    target_question_ids: list[str] = Field(min_length=1)
    authorized_question_ids: list[str] = []
    limits: RequestLimits = RequestLimits()


class GetCandidatePayload(_Strict):
    question_id: str
    variant: Variant | None = None
    candidate_id: str | None = None


class Rejection(_Strict):
    candidate_id: str
    reasons: list[str] = Field(default=[], description="Application-defined codes; the agent stores and forwards them, never interprets a fixed vocabulary.")
    free_text: str | None = None


class RegenerateQuestionPayload(_Strict):
    question_id: str
    rejected: list[Rejection] = []
    limits: RequestLimits = RequestLimits()


class RecordFeedbackPayload(_Strict):
    outcome: Outcome
    candidate_id: str | None = None
    shown: list[str] = Field(default=[], description="Candidate ids actually displayed, in display order (for outcome=shown).")
    alternatives: list[str] = Field(default=[], description="Other candidate ids available but not displayed.")
    reasons: list[str] = []
    free_text: str | None = None
    edited_body: str | None = None
    approve_as_template_id: str | None = Field(default=None, description="For outcome=approved: promote into the reusable template collection under this id.")


class Event(_Strict):
    event_id: str
    session_id: str
    scope_id: str
    type: EventType
    expected_revision: str | None = Field(default=None, description="Revision from the last result; None only for the first prepare_form.")
    payload: dict


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "prepare_form": PrepareFormPayload,
    "update_form": PrepareFormPayload,
    "generate_initial": GenerateInitialPayload,
    "get_candidate": GetCandidatePayload,
    "regenerate_question": RegenerateQuestionPayload,
    "record_feedback": RecordFeedbackPayload,
}


def parse_payload(event: Event) -> BaseModel:
    """Validate the payload against the model for the event type."""
    return PAYLOAD_MODELS[event.type].model_validate(event.payload)


# -- outbound --------------------------------------------------------------------------------

class CandidateOut(_Strict):
    id: str
    question_id: str
    variant: str
    body: str = Field(description="Symbolic template; {{variable_id}} placeholders unresolved.")
    variables: list[str]
    evidence_refs: list[str]
    template_refs: list[str]
    status: str
    form_revision: str
    validation: dict = {}
    self_report: dict = Field(default={}, description="Generator self-assessment. Diagnostic only; not independent verification.")
    ranking: dict | None = None


class Unresolved(_Strict):
    question_id: str
    reason: Literal["insufficient_evidence", "hidden_value_reasoning", "conflicting_evidence", "out_of_scope",
                    "budget_exhausted", "provider_failed", "set_exhausted"]
    needed: str | None = None


class Usage(_Strict):
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    uncertain: int = 0


class Result(_Strict):
    event_id: str
    status: Status
    revision: str | None
    candidates: list[CandidateOut] = Field(default=[], description="Candidates returned for immediate use.")
    cached: dict[str, list[str]] = Field(default={}, description="question_id -> ids of other valid cached candidates.")
    evidence_refs: list[str] = []
    unresolved: list[Unresolved] = []
    usage: Usage = Usage()
    next_action: str | None = None
    diagnostics: list[str] = []


# -- model-facing structured outputs (schema-validated, never free prose) --------------------------

class SelfReport(_Strict):
    confidence: float = Field(ge=0, le=1)
    unsupported_claims: list[str] = []
    dropped_qualifications: list[str] = []


class GeneratedItem(_Strict):
    question_id: str
    variant: Variant
    body: str
    variables: list[str] = []
    evidence_refs: list[str] = []
    template_refs: list[str] = []
    self_report: SelfReport


class Abstention(_Strict):
    question_id: str
    reason: Literal["insufficient_evidence", "hidden_value_reasoning", "conflicting_evidence", "out_of_scope"]
    needed: str


class GenerationOutput(_Strict):
    items: list[GeneratedItem] = []
    abstentions: list[Abstention] = []


class DiagnosisOutput(_Strict):
    question_id: str
    diagnosis: str
    strategy_changes: list[str] = []
    missing_information: list[str] = []
