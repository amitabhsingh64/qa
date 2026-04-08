"""
Session state and evidence directory management.

Each QA run creates a unique session under /sessions/{session_id}/ with:
  - state.json          — current session status, config, progress counters
  - conversations.md    — the shared blackboard (see blackboard.py)
  - site_model.json     — the evolving site graph (see site_model.py)
  - report.json         — structured findings (written at session close)
  - report.md           — human-readable report (written at session close)
  - evidence/           — screenshots, HAR files, console logs by test ID

Session IDs are timestamp-based: {domain}_{YYYYMMDD_HHMMSS}
Example: staging_myapp_com_20260406_143022

Usage (Phase 1+):
    from src.core.session import Session

    session = Session.create(url="https://staging.myapp.com", config=config)
    session.save_evidence("test_login_001", screenshot_bytes)
    session.close(report=report_data)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# TODO: Implement in Phase 1


class SessionState:
    """
    In-memory snapshot of session state, serialised to state.json.

    Fields:
        session_id:      Unique identifier for this session
        url:             Target URL under test
        status:          running | completed | aborted | error
        started_at:      ISO8601 timestamp
        completed_at:    ISO8601 timestamp (None until close)
        pages_visited:   Count of unique pages navigated
        tests_executed:  Count of test steps attempted
        issues_found:    Count of distinct issues logged
        token_usage:     dict with input_tokens, output_tokens, estimated_cost_usd
    """

    # TODO: Implement in Phase 1
    pass


class Session:
    """
    Manages the filesystem state for a single QA run.

    Args:
        session_dir: Path to the session directory (created by Session.create)
    """

    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.evidence_dir = session_dir / "evidence"
        # TODO: Implement in Phase 1

    @classmethod
    def create(cls, url: str, config: Any) -> "Session":
        """
        Create a new session directory and initialise state.json.

        Args:
            url:    Target URL for this session
            config: Loaded Config instance

        Returns:
            New Session instance with session_dir created on disk.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError("Session not yet implemented — see Phase 1")

    @classmethod
    def resume(cls, session_id: str, sessions_root: str | Path = "./sessions") -> "Session":
        """
        Resume an existing session by ID (for crash recovery).

        Args:
            session_id:    Session ID string
            sessions_root: Root sessions directory

        Returns:
            Session instance loaded from existing state.json.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError

    def save_evidence(self, test_id: str, data: bytes, extension: str = "png") -> Path:
        """
        Save a screenshot or other binary evidence file.

        Args:
            test_id:   Test identifier used as filename base
            data:      Binary content to save
            extension: File extension (default 'png')

        Returns:
            Path to the saved evidence file.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError

    def update_state(self, **kwargs: Any) -> None:
        """Update fields in state.json. kwargs are merged into existing state."""
        # TODO: Implement in Phase 1
        raise NotImplementedError

    def close(self, report: dict[str, Any]) -> None:
        """
        Finalise the session: write report.json, report.md, update state status.

        Args:
            report: Structured report dict from the orchestrator.
        """
        # TODO: Implement in Phase 1
        raise NotImplementedError
