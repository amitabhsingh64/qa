"""
Deterministic keyword-to-element-ref matcher (Tier 1 locator).

Strategy: parse the Playwright accessibility snapshot, score every element
against the target intent using keyword matching and heuristics, return the
best-matching element ref with a confidence score.

Handles 80% of element-finding at $0 cost (no LLM call). When confidence
drops below 0.7, the caller should fall back to Tier 2 (LLM + screenshot).

Scoring heuristics (additive, each returns 0.0–1.0 contribution):
  - Exact text match on element label/aria-label/placeholder    (+0.5)
  - Partial text match                                          (+0.3)
  - Role match (e.g. intent="submit" → role=button)            (+0.2)
  - ID/name attribute match                                     (+0.3)
  - Position heuristic (e.g. last button in a form is Submit)  (+0.1)

Confidence thresholds:
  >= 0.7 → use Tier 1 result directly
  <  0.7 → escalate to Tier 2 (LLM fallback)

Usage (Phase 2+):
    from src.core.tier1_locator import Tier1Locator

    locator = Tier1Locator()
    result = locator.find(
        snapshot="<accessibility tree snapshot from Playwright>",
        intent="click the Add to Cart button",
    )
    if result.confidence >= 0.7:
        await mcp_client.call_tool("playwright.browser_click", {"ref": result.ref})
    else:
        # fall back to Tier 2 (vision model)
        ...
"""

from __future__ import annotations

from dataclasses import dataclass

# TODO: Implement in Phase 2


@dataclass
class LocatorResult:
    """Result from a Tier 1 locator lookup."""

    ref: str            # Playwright element ref (e.g. "e45")
    element_text: str   # Human-readable label for logging
    role: str           # ARIA role of the matched element
    confidence: float   # 0.0–1.0; >= 0.7 means Tier 1 is confident
    # TODO: Implement in Phase 2


class Tier1Locator:
    """
    Stateless, deterministic element finder based on keyword scoring.

    No LLM calls. No screenshots. Pure text matching over accessibility snapshots.
    """

    CONFIDENCE_THRESHOLD = 0.7

    def find(self, snapshot: str, intent: str) -> LocatorResult:
        """
        Find the best-matching element in the snapshot for the given intent.

        Args:
            snapshot: Raw accessibility tree text from Playwright browser_snapshot
            intent:   Natural language description of the target element,
                      e.g. "click the Add to Cart button" or "username input field"

        Returns:
            LocatorResult with ref, element_text, role, and confidence score.
            If no match found, returns LocatorResult with ref="" and confidence=0.0.
        """
        # TODO: Implement in Phase 2
        raise NotImplementedError("Tier1Locator not yet implemented — see Phase 2")

    def _score_element(self, element: dict, keywords: list[str]) -> float:
        """
        Score a single parsed element against the extracted keywords.

        Args:
            element:  Dict with keys: ref, role, text, aria_label, placeholder, id, name
            keywords: List of intent keywords to match against

        Returns:
            Confidence score 0.0–1.0.
        """
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def _parse_snapshot(self, snapshot: str) -> list[dict]:
        """
        Parse a Playwright accessibility snapshot into a list of element dicts.

        Args:
            snapshot: Raw accessibility tree text

        Returns:
            List of element dicts with ref, role, text, aria_label, etc.
        """
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def _extract_keywords(self, intent: str) -> list[str]:
        """
        Extract meaningful keywords from an intent string.
        Strips stop words (click, the, a, an, on, into, type).

        Args:
            intent: Natural language intent string

        Returns:
            List of lowercase keywords.
        """
        # TODO: Implement in Phase 2
        raise NotImplementedError
