"""Provider adapters. Every adapter returns a normalized ProviderResult; nothing above this layer sees SDK objects."""
from __future__ import annotations

from answer_cache_agent.providers.base import Credentials, ModelRef, ModelRoles, ProviderAdapter, ProviderResult, parse_json


def build_adapter(ref: ModelRef, credentials: Credentials) -> ProviderAdapter:
    """Construct the adapter for a model reference using runtime-supplied credentials."""
    if ref.provider == "openai":
        from answer_cache_agent.providers.openai import OpenAIAdapter
        return OpenAIAdapter(ref.model, credentials.openai_api_key)
    if ref.provider == "anthropic":
        from answer_cache_agent.providers.anthropic import AnthropicAdapter
        return AnthropicAdapter(ref.model, credentials.anthropic_api_key)
    if ref.provider == "fake":
        from answer_cache_agent.providers.fake import FakeProvider
        return FakeProvider(ref.model)
    raise ValueError(f"unknown provider {ref.provider!r}")


__all__ = ["Credentials", "ModelRef", "ModelRoles", "ProviderAdapter", "ProviderResult", "parse_json", "build_adapter"]
