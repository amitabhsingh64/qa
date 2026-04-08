"""
Agent manifest scanner and validator.

Scans the /agents/ directory at startup, loads every manifest.json,
validates it against the ManifestSchema Pydantic model, cross-checks
required_tools against tools available from connected MCP servers,
and builds an in-memory registry dict keyed by agent_id.

Adding a new agent requires only:
  1. Create /agents/{new_agent}/manifest.json
  2. Create /agents/{new_agent}/skills.md
  No orchestrator code changes needed.

Usage (Phase 1+):
    from src.core.registry import AgentRegistry

    registry = AgentRegistry.load(agents_dir="./agents/", available_tools=tools)
    manifest = registry.get("verifier")
    all_agents = registry.list()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

# TODO: Implement in Phase 1


class ManifestSchema(BaseModel):
    """
    Pydantic schema for agents/{agent_id}/manifest.json.

    All fields are required unless marked Optional.
    """

    id: str
    name: str
    version: str
    type: str                     # orchestrator | generator | verifier | tester | observer
    trigger: str                  # on_demand | per_page_discovery | per_form_discovery |
                                  # per_api_discovery | post_execution | post_load_test
    requires_tools: list[str]     # MCP tool names this agent needs
    model_tier: str               # primary | sub
    input_format: str             # mission_brief_markdown
    output_format: str            # findings_json | test_cases_json
    description: str

    # TODO: Implement in Phase 1 — add validators


class AgentRegistry:
    """
    In-memory registry of all discovered and validated agent manifests.

    Args:
        agents_dir:      Path to the /agents/ directory
        available_tools: Set of tool names currently available from MCP servers
    """

    def __init__(self, agents_dir: Path, available_tools: set[str]) -> None:
        self._agents_dir = agents_dir
        self._available_tools = available_tools
        self._registry: dict[str, ManifestSchema] = {}
        # TODO: Implement in Phase 1

    @classmethod
    def load(cls, agents_dir: str | Path, available_tools: set[str]) -> "AgentRegistry":
        """
        Scan agents_dir, load and validate all manifest.json files.

        Args:
            agents_dir:      Path to /agents/ directory (absolute or relative)
            available_tools: Set of namespaced tool names from connected MCP servers

        Returns:
            Populated AgentRegistry instance.

        Raises:
            ValueError: If any manifest fails validation or requires unavailable tools.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError("AgentRegistry not yet implemented — see Phase 1")

    def get(self, agent_id: str) -> ManifestSchema:
        """
        Retrieve the manifest for a specific agent.

        Args:
            agent_id: Agent identifier (e.g. "verifier", "test_generator")

        Returns:
            ManifestSchema for the agent.

        Raises:
            KeyError: If agent_id not found in registry.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError

    def list(self) -> list[ManifestSchema]:
        """Return all registered agent manifests."""
        # TODO: Implement in Phase 1
        raise NotImplementedError

    def skills_path(self, agent_id: str) -> Path:
        """Return path to the skills.md file for an agent."""
        return self._agents_dir / agent_id / "skills.md"
