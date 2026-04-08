"""
Generic agent execution loop (~400 lines when fully implemented).

Responsibilities:
  - Load agent manifest from /agents/{agent_id}/manifest.json
  - Load agent skills.md as the LLM system prompt
  - Filter available MCP tools to those listed in manifest.requires_tools
  - Route to the correct LLM model based on manifest.model_tier
  - Run the tool-calling loop (max iterations configurable per agent)
  - Return structured output matching manifest.output_format
  - Write findings + intermediate thoughts to the shared blackboard

Usage (Phase 1+):
    from src.core.agent_runner import run_agent
    result = await run_agent(
        agent_id="verifier",
        mission_brief="...",
        session=session,
        mcp_client=mcp_client,
    )

The outer orchestrator loop runs 50-100 iterations.
Sub-agent inner loops run 2-4 iterations.
"""

from __future__ import annotations

# TODO: Implement in Phase 1


class AgentResult:
    """Structured result returned by an agent after its tool loop completes."""

    # TODO: Implement in Phase 1
    # Fields: agent_id, status, findings (list), token_usage, iterations, duration_s
    pass


async def run_agent(
    agent_id: str,
    mission_brief: str,
    session,  # Session instance (Phase 1)
    mcp_client,  # MCPClient instance (Phase 1)
    max_iterations: int = 10,
) -> AgentResult:
    """
    Load the named agent and run its tool-calling loop against the given mission brief.

    Args:
        agent_id:       e.g. "verifier", "test_generator"
        mission_brief:  Markdown string with PRD excerpt, page refs, blackboard observations
        session:        Active session for evidence storage and blackboard access
        mcp_client:     Connected MCP client with available tools
        max_iterations: Safety cap on inner loop iterations (default 10 for sub-agents)

    Returns:
        AgentResult with structured findings and token usage.
    """
    # TODO: Implement in Phase 1
    raise NotImplementedError("AgentRunner not yet implemented — see Phase 1")
