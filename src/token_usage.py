"""
Token usage tracking with Bedrock Converse API pricing.

Accumulates input/output token counts across all API calls in a session,
estimates USD cost, and records per-invocation telemetry for every sub-agent
run regardless of how it ended (complete, capped, or error).
"""

from __future__ import annotations

from datetime import datetime, timezone

# Pricing per million tokens (USD) via AWS Bedrock on-demand
# Matches both bare IDs and cross-region inference profile IDs (us./eu./global. prefix)
_BEDROCK_PRICING: dict[str, tuple[float, float]] = {
    "claude-3-5-sonnet-20241022-v2": (3.00,  15.00),
    "claude-3-5-haiku-20241022-v1":  (0.80,   4.00),
    "claude-3-opus-20240229-v1":     (15.00, 75.00),
    "claude-3-sonnet-20240229-v1":   (3.00,  15.00),
    "claude-3-haiku-20240307-v1":    (0.25,   1.25),
    "claude-opus-4":                 (15.00, 75.00),
    "claude-sonnet-4":               (3.00,  15.00),
    "claude-haiku-4":                (0.80,   4.00),
}
_DEFAULT_PRICING = (3.00, 15.00)  # fall back to Sonnet-class pricing


def _lookup_pricing(model_id: str) -> tuple[float, float]:
    """Match a full Bedrock modelId (including region prefix / :0 suffix) to pricing."""
    for key, pricing in _BEDROCK_PRICING.items():
        if key in model_id:
            return pricing
    return _DEFAULT_PRICING


class TokenUsage:
    """
    Tracks token usage and invocation telemetry for a QA session.

    Two levels of tracking:
    - Aggregate: total input/output tokens + per-agent breakdown (for cost)
    - Invocations: one record per sub-agent run with timing, status, and token delta
    """

    def __init__(self, model: str = "") -> None:
        self.model = model
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        pricing = _lookup_pricing(model)
        self._cost_per_m_input  = pricing[0]
        self._cost_per_m_output = pricing[1]

        # Per-agent aggregate: {agent_id: {"input": N, "output": N}}
        self._breakdown: dict[str, dict[str, int]] = {}

        # Invocation log: one entry per sub-agent run
        self._invocations: list[dict] = []
        self._invocation_counter: int = 0

    # ------------------------------------------------------------------
    # Token accumulation
    # ------------------------------------------------------------------

    def add(self, usage: dict | None, agent_id: str = "orchestrator") -> None:
        """
        Record token counts from a Bedrock Converse response usage dict.

        Args:
            usage:    Dict with ``inputTokens`` / ``outputTokens`` keys.
                      Silently ignored if None.
            agent_id: Which agent made this call. Defaults to "orchestrator".
        """
        if not usage:
            return
        inp = usage.get("inputTokens", 0) or 0
        out = usage.get("outputTokens", 0) or 0
        self.input_tokens += inp
        self.output_tokens += out
        entry = self._breakdown.setdefault(agent_id, {"input": 0, "output": 0})
        entry["input"] += inp
        entry["output"] += out

    def snapshot_tokens(self, agent_id: str) -> dict[str, int]:
        """
        Return a copy of the current token counts for agent_id.

        Call before a sub-agent run starts; diff against the result of
        a second call after it ends to get per-invocation token counts.
        """
        entry = self._breakdown.get(agent_id, {"input": 0, "output": 0})
        return {"input": entry["input"], "output": entry["output"]}

    # ------------------------------------------------------------------
    # Invocation recording (two-step: begin before call, close after)
    # ------------------------------------------------------------------

    def begin_invocation(
        self,
        agent_id: str,
        attempt: int,
        previous_invocation_id: str | None,
        started_at: datetime,
    ) -> str:
        """
        Open a new invocation record immediately before the LLM call starts.

        Creates a partial record with status="running" so the invocation is
        tracked even if the call raises an exception. Call close_invocation()
        to fill in the final status, timing, and token delta.

        Returns:
            The generated invocation_id string.
        """
        self._invocation_counter += 1
        inv_id = f"inv_{self._invocation_counter:03d}"
        self._invocations.append({
            "invocation_id":          inv_id,
            "agent_id":               agent_id,
            "attempt":                attempt,
            "previous_invocation_id": previous_invocation_id,
            "status":                 "running",
            "iterations_used":        0,
            "iterations_limit":       None,
            "started_at":             started_at.isoformat(),
            "duration_seconds":       None,
            "tokens":                 None,
        })
        return inv_id

    def close_invocation(
        self,
        inv_id: str,
        status: str,
        iterations_used: int,
        iterations_limit: int,
        started_at: datetime,
        tokens_before: dict[str, int],
        capped_summary: dict | None = None,
        retry_scope: dict | None = None,
    ) -> None:
        """
        Finalize an invocation record opened by begin_invocation().

        Args:
            inv_id:          The id returned by begin_invocation().
            status:          "complete" | "capped" | "error"
            iterations_used: How many loop iterations ran.
            iterations_limit: The agent's max_iterations cap.
            started_at:      datetime when the invocation started (for duration).
            tokens_before:   Snapshot from snapshot_tokens() taken before the run.
            capped_summary:  Optional metadata dict when status is "capped".
            retry_scope:     Optional retry targeting metadata (only set when attempt > 1).
        """
        record = next(
            (r for r in self._invocations if r["invocation_id"] == inv_id), None
        )
        if record is None:
            return  # should not happen

        agent_id = record["agent_id"]
        now = datetime.now(timezone.utc)
        after = self._breakdown.get(agent_id, {"input": 0, "output": 0})

        record["status"]           = status
        record["iterations_used"]  = iterations_used
        record["iterations_limit"] = iterations_limit
        record["duration_seconds"] = round((now - started_at).total_seconds(), 3)
        record["tokens"] = {
            "input":  after["input"]  - tokens_before["input"],
            "output": after["output"] - tokens_before["output"],
        }
        if capped_summary is not None:
            record["capped_summary"] = capped_summary
        if retry_scope is not None:
            record["retry_scope"] = retry_scope

    def get_invocations(self, agent_id: str | None = None) -> list[dict]:
        """
        Return invocation records, optionally filtered by agent_id.

        Args:
            agent_id: If provided, return only records for this agent.
                      If None, return all records.
        """
        if agent_id is None:
            return list(self._invocations)
        return [r for r in self._invocations if r["agent_id"] == agent_id]

    # ------------------------------------------------------------------
    # Cost helpers
    # ------------------------------------------------------------------

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        return round(
            (self.input_tokens  / 1_000_000) * self._cost_per_m_input
            + (self.output_tokens / 1_000_000) * self._cost_per_m_output,
            6,
        )

    def agent_cost_usd(self, agent_id: str) -> float:
        """Return estimated USD cost for a single agent's aggregate token usage."""
        entry = self._breakdown.get(agent_id, {"input": 0, "output": 0})
        return round(
            (entry["input"]  / 1_000_000) * self._cost_per_m_input
            + (entry["output"] / 1_000_000) * self._cost_per_m_output,
            6,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        breakdown_with_cost = {
            aid: {
                "input_tokens":       v["input"],
                "output_tokens":      v["output"],
                "estimated_cost_usd": self.agent_cost_usd(aid),
            }
            for aid, v in self._breakdown.items()
        }
        return {
            "model":               self.model,
            "input_tokens":        self.input_tokens,
            "output_tokens":       self.output_tokens,
            "total_tokens":        self.total_tokens,
            "estimated_cost_usd":  self.estimated_cost_usd,
            "pricing": {
                "input_per_M_usd":  self._cost_per_m_input,
                "output_per_M_usd": self._cost_per_m_output,
            },
            "breakdown_by_agent":  breakdown_with_cost,
            "agent_invocations":   self._invocations,
        }
