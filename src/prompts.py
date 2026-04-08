"""
Prompt builders for the QA orchestrator.

The orchestrator's system prompt (skills + heuristics) lives in
agents/orchestrator/skills.md and is loaded dynamically by runner.py.
This module only builds the initial user message that starts the session.
"""

from __future__ import annotations


def build_orchestrator_prompt(url: str, prd_content: str) -> str:
    """
    Build the initial user message sent to the orchestrator at session start.

    Args:
        url:         Target URL to test.
        prd_content: PRD/requirements text (empty string if not provided).

    Returns:
        Formatted prompt string.
    """
    prd_section = (
        f"## Product Requirements Document\n\n{prd_content}"
        if prd_content
        else "## Product Requirements Document\n\nNot provided."
    )

    return (
        f"## QA Session\n\n"
        f"**Target URL:** {url}\n\n"
        f"{prd_section}\n\n"
        f"## Instructions\n\n"
        f"Begin the two-phase QA session for the target URL above.\n\n"
        f"**Phase 1:** Invoke the crawler to map the site.\n"
        f"**Phase 2:** Use the site map to invoke test_generator, then verifier, "
        f"then report_generator.\n\n"
        f"Follow the mission brief templates in your skills. "
        f"Pass all relevant context (URL, PRD, prior agent results) in each mission brief."
    )
