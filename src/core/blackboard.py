"""
Append-only shared conversation log (the blackboard).

Every agent writes observations, findings, and decisions to a shared
conversations.md file inside the active session directory. The orchestrator
reads curated excerpts from it when building mission briefs for sub-agents.

Design rules:
  - Writes are ALWAYS appends — nothing is ever deleted or overwritten
  - Each entry is timestamped and tagged with the author agent and entry type
  - The query() method returns filtered excerpts to keep sub-agent context lean
  - Full audit trail is preserved for post-session debugging

Entry types:
  - "observation"  — factual page/element discovery (e.g. "Found login form")
  - "finding"      — a potential bug or issue with severity
  - "plan"         — a list of steps the orchestrator intends to take
  - "result"       — outcome of a test step (PASS/FAIL/FLAKY)
  - "error"        — unexpected runtime error

Usage (Phase 1+):
    from src.core.blackboard import Blackboard

    bb = Blackboard(session_dir="/sessions/abc123/")
    bb.append(author="orchestrator", type="observation", content="Found checkout form at /cart")
    recent = bb.query(types=["finding"], limit=10)
"""

from __future__ import annotations

from pathlib import Path

# TODO: Implement in Phase 1


class BlackboardEntry:
    """A single timestamped entry on the blackboard."""

    # TODO: Implement in Phase 1
    # Fields: timestamp (ISO8601), author (agent_id), type, content
    pass


class Blackboard:
    """
    Append-only shared log stored as conversations.md in the session directory.

    Args:
        session_dir: Path to the active session directory.
    """

    def __init__(self, session_dir: Path | str) -> None:
        self.session_dir = Path(session_dir)
        self._path = self.session_dir / "conversations.md"
        # TODO: Implement in Phase 1

    def append(self, author: str, type: str, content: str) -> BlackboardEntry:
        """
        Append a new entry to the blackboard.

        Args:
            author:  Agent ID writing this entry (e.g. "orchestrator", "verifier")
            type:    Entry type — one of observation/finding/plan/result/error
            content: Free-text or structured markdown content

        Returns:
            The created BlackboardEntry.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError("Blackboard not yet implemented — see Phase 1")

    def query(
        self,
        types: list[str] | None = None,
        author: str | None = None,
        limit: int = 20,
    ) -> list[BlackboardEntry]:
        """
        Return filtered entries from the blackboard, most recent first.

        Args:
            types:  Filter to these entry types (None = all types)
            author: Filter to entries by this agent (None = all agents)
            limit:  Maximum number of entries to return

        Returns:
            List of BlackboardEntry objects matching the filters.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError

    def full_text(self) -> str:
        """Return the complete conversations.md content as a string."""
        # TODO: Implement in Phase 1
        raise NotImplementedError
