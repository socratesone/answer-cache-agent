from __future__ import annotations

from answer_cache_agent.providers.base import REQUEST_TIMEOUT_S, ProviderResult, message_text, parse_json


class OpenAIAdapter:
    """Chat Completions with JSON-schema response format; normalizes refusal, length, and malformed output."""

    def __init__(self, model_id: str, api_key: str | None) -> None:
        from langchain_openai import ChatOpenAI

        self.model_id = model_id
        self._factory = lambda max_tokens, schema: ChatOpenAI(
            model=model_id, api_key=api_key, max_tokens=max_tokens, temperature=0, max_retries=0, timeout=REQUEST_TIMEOUT_S,
            model_kwargs={"response_format": {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}}},
        )

    def complete_json(self, system: str, user: str, schema: dict, max_output_tokens: int) -> ProviderResult:
        try:
            msg = self._factory(max_output_tokens, schema).invoke([("system", system), ("user", user)])
        except Exception as exc:  # network, auth, rate limit: usage unknown
            return ProviderResult("error", self.model_id, error=f"{type(exc).__name__}: {exc}")
        usage = msg.usage_metadata or {}
        base = dict(model_id=self.model_id, input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                    meta={"finish_reason": msg.response_metadata.get("finish_reason")})
        if msg.additional_kwargs.get("refusal"):
            return ProviderResult("refusal", raw_text=msg.additional_kwargs["refusal"], **base)
        text = message_text(msg.content)
        if base["meta"]["finish_reason"] in ("length", "content_filter"):
            return ProviderResult("truncated" if base["meta"]["finish_reason"] == "length" else "refusal", raw_text=text, **base)
        data = parse_json(text)
        return ProviderResult("ok" if data is not None else "malformed", data=data, raw_text=text, **base)
