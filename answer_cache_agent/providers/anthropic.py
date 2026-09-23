from __future__ import annotations

import json

from answer_cache_agent.providers.base import REQUEST_TIMEOUT_S, ProviderResult, message_text, parse_json


class AnthropicAdapter:
    """Messages API; schema is enforced by instruction + local validation. Normalizes stop_reason max_tokens/refusal."""

    def __init__(self, model_id: str, api_key: str | None) -> None:
        from langchain_anthropic import ChatAnthropic

        self.model_id = model_id
        # No sampling params: current Claude models reject temperature/top_p/top_k with a 400.
        self._factory = lambda max_tokens: ChatAnthropic(model=model_id, api_key=api_key, max_tokens=max_tokens, max_retries=0,
                                                         timeout=REQUEST_TIMEOUT_S)

    def complete_json(self, system: str, user: str, schema: dict, max_output_tokens: int) -> ProviderResult:
        system_full = f"{system}\n\nRespond with a single JSON object matching this JSON Schema and nothing else:\n{json.dumps(schema)}"
        try:
            msg = self._factory(max_output_tokens).invoke([("system", system_full), ("user", user)])
        except Exception as exc:
            return ProviderResult("error", self.model_id, error=f"{type(exc).__name__}: {exc}")
        usage = msg.usage_metadata or {}
        stop = msg.response_metadata.get("stop_reason")
        base = dict(model_id=self.model_id, input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                    meta={"stop_reason": stop})
        text = message_text(msg.content)
        if stop == "refusal":
            return ProviderResult("refusal", raw_text=text, **base)
        if stop == "max_tokens":
            return ProviderResult("truncated", raw_text=text, **base)
        data = parse_json(text)
        return ProviderResult("ok" if data is not None else "malformed", data=data, raw_text=text, **base)
