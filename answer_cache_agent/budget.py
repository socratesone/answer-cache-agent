"""Paid-call gate: check limits, reserve in the ledger, leak-check the payload, send, confirm or mark uncertain."""
from __future__ import annotations

import uuid
from collections.abc import Mapping

from answer_cache_agent.config import Config
from answer_cache_agent.contracts import RequestLimits
from answer_cache_agent.providers.base import ProviderAdapter, ProviderResult
from answer_cache_agent.rendering import find_leaks
from answer_cache_agent.repository import Repository


class PaidCallGate:
    def __init__(self, repo: Repository, cfg: Config, session_id: str, event_id: str,
                 limits: RequestLimits, bindings: Mapping[str, str]) -> None:
        self.repo, self.cfg, self.session_id, self.event_id = repo, cfg, session_id, event_id
        self.limits, self.bindings = limits, bindings
        self.calls_this_op = 0
        self.tokens_this_op = 0
        self.diagnostics: list[str] = []

    def refusal(self, est_tokens: int) -> str | None:
        """Why the next paid call may not proceed, or None."""
        b, u = self.cfg.budget, self.repo.session_usage(self.session_id)
        if self.calls_this_op >= b.max_paid_calls_per_operation:
            return f"max_paid_calls_per_operation={b.max_paid_calls_per_operation} reached"
        if u["tokens"] + est_tokens > b.max_session_tokens:
            return f"session tokens {u['tokens']}+{est_tokens} > {b.max_session_tokens}"
        if u["cost_usd"] >= b.max_session_cost_usd:
            return f"session cost {u['cost_usd']:.4f} >= {b.max_session_cost_usd}"
        if self.limits.max_tokens is not None and self.tokens_this_op + est_tokens > self.limits.max_tokens:
            return f"request max_tokens {self.limits.max_tokens} would be exceeded"
        if self.limits.max_cost_usd is not None and self._cost_this_op() >= self.limits.max_cost_usd:
            return f"request max_cost_usd {self.limits.max_cost_usd} reached"
        return None

    def call(self, role: str, adapter: ProviderAdapter, system: str, user: str, schema: dict, max_out: int) -> ProviderResult:
        est_in = (len(system) + len(user)) // self.cfg.budget.chars_per_token_estimate
        why = self.refusal(est_in + max_out)
        if why:
            return ProviderResult("error", adapter.model_id, error=f"budget: {why}", meta={"budget_refused": True})
        leaked = find_leaks(system + user, self.bindings)
        if leaked:
            return ProviderResult("error", adapter.model_id, error=f"leak check blocked outbound payload: {leaked}", meta={"leak": True})
        call_id = str(uuid.uuid4())
        self.repo.reserve_call(call_id, self.event_id, self.session_id, role, adapter.model_id, est_in, max_out)
        self.calls_this_op += 1
        try:
            r = adapter.complete_json(system, user, schema, max_out)
        except BaseException:
            # Process may die here; the row must not stay 'reserved' and must never be re-sent blindly.
            self.repo.mark_uncertain(call_id)
            raise
        if r.usage_known:
            self.repo.confirm_call(call_id, r.input_tokens, r.output_tokens, self._cost(adapter.model_id, r.input_tokens, r.output_tokens))
            self.tokens_this_op += r.input_tokens + r.output_tokens
        else:
            # Request may or may not have been billed; count at estimate, never zero, never auto-retry.
            self.repo.mark_uncertain(call_id)
            self.tokens_this_op += est_in + max_out
        return r

    def _cost(self, model_id: str, tin: int, tout: int) -> float | None:
        p = self.cfg.pricing.get(model_id)
        if p is None:
            self.diagnostics.append(f"no pricing for {model_id}; cost guard is tokens-only")
            return None
        return (tin * p.input + tout * p.output) / 1_000_000

    def _cost_this_op(self) -> float:
        return self.repo.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM usage_ledger WHERE event_id=?", (self.event_id,)).fetchone()[0]
