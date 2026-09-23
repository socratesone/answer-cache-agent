"""Deterministic ranking (Q4): hard filters, sourced components, capped linear score, back-off preference."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from answer_cache_agent.config import RankingConfig

GLOBAL_KEY = "*"


def context_key(values: set[str]) -> str:
    return "|".join(sorted(values)) if values else GLOBAL_KEY


def backoff_keys(values: set[str]) -> list[str]:
    """Joint key, then each single value, then global. Duplicates removed in order."""
    keys = [context_key(values)] + [context_key({v}) for v in sorted(values)] + [GLOBAL_KEY]
    seen: list[str] = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    return seen


@dataclass
class Stats:
    sel: float = 0.0
    rej: float = 0.0
    edit: float = 0.0
    shown: float = 0.0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def decayed(self, now: datetime, half_life_days: float) -> "Stats":
        age_days = max(0.0, (now - self.updated_at).total_seconds() / 86400)
        f = 0.5 ** (age_days / half_life_days)
        return Stats(self.sel * f, self.rej * f, self.edit * f, self.shown * f, now)


def apply_outcome(stats: Stats, outcome: str, now: datetime, cfg: RankingConfig) -> Stats:
    """Decay then increment. Exposure without an outcome touches only `shown`."""
    s = stats.decayed(now, cfg.half_life_days)
    if outcome == "selected":
        s.sel += 1
    elif outcome == "rejected":
        s.rej += 1
    elif outcome == "edited":
        s.edit += 1
    elif outcome == "shown":
        s.shown += 1
    return s


PRIOR_KEY = "prior"


def preference(lookup, form_values: set[str], now: datetime, cfg: RankingConfig) -> tuple[float, str]:
    """Beta posterior mean at the first back-off key with enough observations. Returns (score, key_used).

    The global key is consulted only when the form carries no context at all: a known-but-sparse context
    must not inherit preferences learned elsewhere (PRD §7, 'unrelated full-stack applications').
    """
    for key in backoff_keys(form_values):
        if key == GLOBAL_KEY and form_values:
            break
        s = lookup(key)
        s = s.decayed(now, cfg.half_life_days) if s else Stats(updated_at=now)
        n = s.sel + s.rej + s.edit
        if n >= cfg.min_n or key == GLOBAL_KEY:
            wins = s.sel + cfg.edit_weight * s.edit
            return (wins + cfg.alpha) / (n + cfg.alpha + cfg.beta), key
    return cfg.alpha / (cfg.alpha + cfg.beta), PRIOR_KEY


def requires_satisfied(required: dict[str, set[str]], form: dict[str, set[str]]) -> bool:
    """Hard filter: every `requires` dimension must intersect the form's values on that dimension."""
    return all(required[d] & form.get(d, set()) for d in required)


def ctx_match(applies: dict[str, set[str]], form: dict[str, set[str]]) -> float:
    """Known dimensions only; a template silent on a known dimension is neutral on it."""
    known = [d for d, vals in form.items() if vals]
    if not known:
        return 0.5
    hits = sum(1 for d in known if applies.get(d) and applies[d] & form[d])
    miss = sum(1 for d in known if applies.get(d) and not (applies[d] & form[d]))
    return min(1.0, max(0.0, 0.5 + 0.5 * (hits - miss) / len(known)))


def score(semantic: float, context: float, quality: float, pref: float, cfg: RankingConfig) -> dict:
    """Capped linear combination; returns every component so the ordering is inspectable."""
    w = cfg.weights
    pref_w = w.preference if cfg.learning_enabled else 0.0
    total = w.semantic * semantic + w.context * context + w.quality * quality + pref_w * pref
    return {
        "score": round(total, 6),
        "semantic": semantic, "context": context, "quality": quality, "preference": pref,
        "weights": {"semantic": w.semantic, "context": w.context, "quality": w.quality, "preference": pref_w},
        "policy_version": cfg.policy_version,
    }


def _assert_examples() -> None:
    cfg = RankingConfig(policy_version="t", weights={"semantic": .4, "context": .25, "quality": .2, "preference": .15},
                        alpha=1, beta=1, min_n=3, half_life_days=90, edit_weight=.5, learning_enabled=True)
    form = {"role_family": {"agent_engineering"}, "sector": {"education"}}
    assert ctx_match({"role_family": {"full_stack"}}, form) == 0.25
    assert ctx_match({"role_family": {"agent_engineering"}}, form) == 0.75
    assert ctx_match({}, form) == 0.5
    assert ctx_match({"sector": {"education"}}, {}) == 0.5
    assert requires_satisfied({"sector": {"education"}}, form)
    assert not requires_satisfied({"sector": {"education"}}, {"role_family": {"full_stack"}})
    now = datetime.now(timezone.utc)
    s = Stats(sel=3, updated_at=now)
    p, key = preference(lambda k: s if k == "agent_engineering|education" else None, {"agent_engineering", "education"}, now, cfg)
    assert math.isclose(p, 0.8) and key == "agent_engineering|education"
    p, key = preference(lambda k: s if k == GLOBAL_KEY else None, {"full_stack"}, now, cfg)
    assert p == 0.5 and key == PRIOR_KEY  # global stats never leak into a known context
    p, key = preference(lambda k: s if k == GLOBAL_KEY else None, set(), now, cfg)
    assert math.isclose(p, 0.8) and key == GLOBAL_KEY
    assert score(1, 1, 1, 1, cfg)["score"] == 1.0


if __name__ == "__main__":
    _assert_examples()
    print("ranking self-check ok")
