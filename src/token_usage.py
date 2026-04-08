"""
Token usage tracking with Bedrock Converse API pricing.

Accumulates input/output token counts across all API calls in a session
and estimates USD cost based on the active model. Supports per-agent
breakdown so costs can be attributed to each sub-agent after the session.
"""

from __future__ import annotations

# Pricing per million tokens (USD) via AWS Bedrock on-demand
# Keys match Bedrock modelId prefixes (suffix :0 stripped for lookup).
# Update as AWS publishes new rates.
_BEDROCK_PRICING: dict[str, tuple[float, float]] = {
    # modelId prefix: (input_cost_per_M, output_cost_per_M)
    # Matches both bare IDs and cross-region inference profile IDs (us./eu./ap. prefix)
    "claude-3-5-sonnet-20241022-v2": (3.00, 15.00),
    "claude-3-5-haiku-20241022-v1":  (0.80,  4.00),
    "claude-3-opus-20240229-v1":     (15.00, 75.00),
    "claude-3-sonnet-20240229-v1":   (3.00, 15.00),
    "claude-3-haiku-20240307-v1":    (0.25,  1.25),
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
    Accumulates token usage across all Bedrock API calls in the session.

    Supports per-agent attribution: pass agent_id to add() to record which
    agent consumed which tokens. Access the breakdown via agent_breakdown.
    """

    def __init__(self, model: str = "") -> None:
        self.model = model
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        pricing = _lookup_pricing(model)
        self._cost_per_m_input = pricing[0]
        self._cost_per_m_output = pricing[1]
        # Per-agent breakdown: {agent_id: {"input": N, "output": N}}
        self._breakdown: dict[str, dict[str, int]] = {}

    def add(self, usage: dict | None, agent_id: str = "orchestrator") -> None:
        """
        Record token counts from a Bedrock Converse ``usage`` dict.

        Args:
            usage:    Dict with ``inputTokens`` / ``outputTokens`` keys as
                      returned by ``response['usage']``. Silently ignored if None.
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

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        input_cost = (self.input_tokens / 1_000_000) * self._cost_per_m_input
        output_cost = (self.output_tokens / 1_000_000) * self._cost_per_m_output
        return round(input_cost + output_cost, 6)

    def agent_cost_usd(self, agent_id: str) -> float:
        """Return estimated USD cost for a single agent's token usage."""
        entry = self._breakdown.get(agent_id, {"input": 0, "output": 0})
        return round(
            (entry["input"] / 1_000_000) * self._cost_per_m_input
            + (entry["output"] / 1_000_000) * self._cost_per_m_output,
            6,
        )

    def to_dict(self) -> dict:
        breakdown_with_cost = {
            aid: {
                "input_tokens": v["input"],
                "output_tokens": v["output"],
                "estimated_cost_usd": self.agent_cost_usd(aid),
            }
            for aid, v in self._breakdown.items()
        }
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "pricing": {
                "input_per_M_usd": self._cost_per_m_input,
                "output_per_M_usd": self._cost_per_m_output,
            },
            "breakdown_by_agent": breakdown_with_cost,
        }
