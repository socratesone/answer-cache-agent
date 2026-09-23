"""Validated tunables loaded from one YAML file."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_PATH = Path(__file__).with_name("config.yaml")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchConfig(_Strict):
    max_questions_per_batch: int = Field(ge=1)


class RetrievalConfig(_Strict):
    top_k: int = Field(ge=1)
    min_similarity: float = Field(ge=-1, le=1)
    max_context_tokens_per_question: int = Field(ge=100)
    embedding_model: str


class RankingWeights(_Strict):
    semantic: float = Field(ge=0, le=1)
    context: float = Field(ge=0, le=1)
    quality: float = Field(ge=0, le=1)
    preference: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sums_to_one(self) -> "RankingWeights":
        total = self.semantic + self.context + self.quality + self.preference
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ranking weights must sum to 1.0, got {total}")
        return self


class RankingConfig(_Strict):
    policy_version: str
    weights: RankingWeights
    alpha: float = Field(gt=0)
    beta: float = Field(gt=0)
    min_n: int = Field(ge=0)
    half_life_days: float = Field(gt=0)
    edit_weight: float = Field(ge=0, le=1)
    learning_enabled: bool


class GenerationConfig(_Strict):
    max_regen_rounds_before_feedback: int = Field(ge=1)
    max_output_tokens_per_question: int = Field(ge=50)
    max_output_tokens_per_call: int = Field(ge=100)


class BudgetConfig(_Strict):
    max_session_cost_usd: float = Field(ge=0)
    max_session_tokens: int = Field(ge=0)
    max_paid_calls_per_operation: int = Field(ge=1)
    chars_per_token_estimate: int = Field(ge=1)


class Price(_Strict):
    input: float = Field(ge=0)
    output: float = Field(ge=0)


class EvaluatorConfig(_Strict):
    enabled: bool


class RetentionConfig(_Strict):
    unseen_candidate_days: int = Field(ge=0)
    shown_candidate_days: int = Field(ge=0)
    rejected_candidate_days: int = Field(ge=0)
    invalid_candidate_days: int = Field(ge=0)


class Config(_Strict):
    version: int
    batch: BatchConfig
    retrieval: RetrievalConfig
    ranking: RankingConfig
    generation: GenerationConfig
    budget: BudgetConfig
    pricing: dict[str, Price] = {}
    evaluator: EvaluatorConfig
    retention: RetentionConfig


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate the tunables file; unknown keys are rejected."""
    with open(path or DEFAULT_PATH, encoding="utf-8") as fh:
        return Config.model_validate(yaml.safe_load(fh))
