"""Scripted provider for tests and the offline harness. Records every outbound payload for leak checks."""
from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable

from answer_cache_agent.providers.base import ProviderResult


class FakeProvider:
    def __init__(self, model_id: str = "fake-1", script: list[ProviderResult | Callable[[str, str], ProviderResult]] | None = None) -> None:
        self.model_id = model_id
        self.script: deque = deque(script or [])
        self.calls: list[dict] = []

    def complete_json(self, system: str, user: str, schema: dict, max_output_tokens: int) -> ProviderResult:
        self.calls.append({"system": system, "user": user, "max_output_tokens": max_output_tokens})
        if not self.script:
            return ProviderResult("error", self.model_id, error="fake provider script exhausted")
        step = self.script.popleft()
        r = step(system, user) if callable(step) else step
        r.model_id = r.model_id or self.model_id
        return r

    @staticmethod
    def ok(data: dict, input_tokens: int = 100, output_tokens: int = 50) -> ProviderResult:
        return ProviderResult("ok", "", data=data, input_tokens=input_tokens, output_tokens=output_tokens)


def demo_generator(system: str, user: str) -> ProviderResult:
    """Deterministic stand-in model: cites the top-ranked template/evidence, uses only permitted variables, abstains on empty bundles."""
    u = json.loads(user)
    b = u["CONTEXT BUNDLE"]
    qid = b["question"]["id"]
    if not b["templates"] and not b["evidence"]:
        return FakeProvider.ok({"items": [], "abstentions": [{"question_id": qid, "reason": "insufficient_evidence", "needed": "any approved material"}]})
    refs = dict(template_refs=[b["templates"][0]["id"]] if b["templates"] else [],
                evidence_refs=[b["evidence"][0]["id"]] if b["evidence"] else [])
    base = b["templates"][0]["body"] if b["templates"] else b["evidence"][0]["excerpt"]
    used = [v["id"] for v in u["PERMITTED VARIABLES"] if "{{" + v["id"] + "}}" in base]
    rep = {"confidence": 0.85}
    if "TARGET QUESTIONS" in u:
        items = [dict(question_id=qid, variant="standard", body=base, variables=used, self_report=rep, **refs),
                 dict(question_id=qid, variant="concise", body=base.split(". ")[0].rstrip(".") + ".", variables=used, self_report=rep, **refs)]
    else:
        notes = ";".join(",".join(r["reasons"]) for r in u["REJECTED"]) or "none"
        diag = (u.get("DIAGNOSIS") or {}).get("diagnosis", "")
        items = [dict(question_id=qid, variant="alternative", body=f"{base} (alt {i}; addressing: {notes}{'; ' + diag if diag else ''})",
                      variables=used, self_report=rep, **refs) for i in range(1, 4)]
    return FakeProvider.ok({"items": items, "abstentions": []})


def demo_diagnoser(system: str, user: str) -> ProviderResult:
    u = json.loads(user)
    reasons = sorted({r for c in u["rejected_candidates"] for r in c.get("reasons", [])})
    return FakeProvider.ok({"question_id": u["question"]["id"], "diagnosis": f"rejections cluster on {reasons or ['no reasons']}",
                            "strategy_changes": ["change emphasis to what the reasons point at"], "missing_information": []})


def demo_provider(model_id: str = "fake-1", diagnoser: bool = False, n: int = 1000) -> FakeProvider:
    return FakeProvider(model_id, [demo_diagnoser if diagnoser else demo_generator] * n)
