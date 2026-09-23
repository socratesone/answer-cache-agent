"""Templates are data. Placeholder detection, authorization, local substitution, post-substitution checks, leak check."""
from __future__ import annotations

import re
from collections.abc import Mapping

from answer_cache_agent.contracts import Constraints

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_MIN_LEAK_LEN = 3


def referenced_variables(body: str) -> list[str]:
    """Distinct variable ids in order of first appearance."""
    seen: list[str] = []
    for m in PLACEHOLDER.finditer(body):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def unauthorized_variables(body: str, allowed: set[str]) -> list[str]:
    return [v for v in referenced_variables(body) if v not in allowed]


def render(body: str, bindings: Mapping[str, str]) -> str:
    """Plain substitution; no expressions, no functions. Missing binding raises KeyError."""
    return PLACEHOLDER.sub(lambda m: bindings[m.group(1)], body)


def check_constraints(rendered: str, c: Constraints) -> list[str]:
    """Violations after substitution (PRD §8: a short template with a long value can still overflow)."""
    out = []
    if c.max_length is not None and len(rendered) > c.max_length:
        out.append(f"length {len(rendered)} > {c.max_length}")
    if c.max_words is not None and (n := len(rendered.split())) > c.max_words:
        out.append(f"words {n} > {c.max_words}")
    if c.required and not rendered.strip():
        out.append("required but empty")
    return out


def find_leaks(text: str, bindings: Mapping[str, str]) -> list[str]:
    """Variable ids whose private value appears verbatim in outbound/telemetry text."""
    return [k for k, v in bindings.items() if len(v) >= _MIN_LEAK_LEN and v in text]


if __name__ == "__main__":
    b = "{{v17}} and {{ v2 }} and {{v17}}"
    assert referenced_variables(b) == ["v17", "v2"]
    assert unauthorized_variables(b, {"v17"}) == ["v2"]
    assert render("Hi {{name}}.", {"name": "Ada"}) == "Hi Ada."
    assert check_constraints("a" * 11, Constraints(max_length=10)) == ["length 11 > 10"]
    assert find_leaks("call 555-0100 now", {"phone": "555-0100", "y": "no"}) == ["phone"]
    print("rendering self-check ok")
