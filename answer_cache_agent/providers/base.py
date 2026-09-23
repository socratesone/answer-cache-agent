from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

ResultStatus = Literal["ok", "refusal", "truncated", "malformed", "error"]
REQUEST_TIMEOUT_S = 60  # a hung connection must not block the single-threaded agent forever


@dataclass(frozen=True)
class ModelRef:
    provider: Literal["openai", "anthropic", "fake"]
    model: str


@dataclass(frozen=True)
class ModelRoles:
    """Owner-configured roles (PRD §11). Both may point at the same model."""
    routine: ModelRef
    advanced: ModelRef

    def get(self, role: str) -> ModelRef:
        return self.routine if role == "routine" else self.advanced


@dataclass(frozen=True)
class Credentials:
    """Supplied by the trusted runtime; never read from event payloads, never checkpointed."""
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None


@dataclass
class ProviderResult:
    status: ResultStatus
    model_id: str
    data: dict | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_text: str = ""
    error: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def usage_known(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None


@runtime_checkable
class ProviderAdapter(Protocol):
    model_id: str

    def complete_json(self, system: str, user: str, schema: dict, max_output_tokens: int) -> ProviderResult: ...


def parse_json(text: str) -> dict | None:
    """Tolerate a fenced block; anything else non-JSON is malformed."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[4:] if t.startswith("json") else t
    try:
        obj = json.loads(t)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def message_text(content) -> str:
    """LangChain content may be a string or a list of blocks."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
