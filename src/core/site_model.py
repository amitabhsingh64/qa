"""
Site graph data structure.

Represents the orchestrator's accumulated knowledge about a website:
  - pages[]          — discovered URLs with titles, HTTP status, tech stack flags
  - forms[]          — discovered forms with field names, action URLs, methods
  - nav_edges[]      — links between pages (for graph traversal)
  - auth_boundaries  — pages that redirect to login when accessed unauthenticated
  - api_endpoints[]  — XHR/fetch requests observed during navigation
  - tech_stack       — detected technologies (React, Next.js, Vue, Stripe, etc.)

The site model is written to site_model.json in the session directory as it
is built during discovery, and optionally persisted to site-models/{domain}.json
for incremental testing in future runs.

Schema versioning: every site-models/{domain}.json includes a "schema_version"
field. Migrations run on load when schema_version < current.

Usage (Phase 2+):
    from src.core.site_model import SiteModel, Page, Form

    model = SiteModel(base_url="https://staging.myapp.com")
    model.add_page(Page(url="/", title="Home", status=200))
    model.add_form(Form(page_url="/login", fields=["username", "password"]))
    model.save(session.session_dir / "site_model.json")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# TODO: Implement in Phase 2

SCHEMA_VERSION = 1


@dataclass
class Page:
    """A single discovered page in the site graph."""

    url: str
    title: str = ""
    status: int = 200
    is_auth_wall: bool = False
    tech_signals: list[str] = field(default_factory=list)  # e.g. ["react", "next.js"]
    # TODO: Implement in Phase 2


@dataclass
class Form:
    """A discovered HTML form."""

    page_url: str
    action: str = ""
    method: str = "POST"
    fields: list[str] = field(default_factory=list)
    has_csrf_token: bool = False
    # TODO: Implement in Phase 2


@dataclass
class NavEdge:
    """A link between two pages."""

    source_url: str
    target_url: str
    link_text: str = ""
    # TODO: Implement in Phase 2


@dataclass
class ApiEndpoint:
    """An API endpoint observed in browser network traffic."""

    url: str
    method: str = "GET"
    observed_on: str = ""   # page URL where this request was seen
    status: int = 0
    # TODO: Implement in Phase 2


class SiteModel:
    """
    Mutable site graph built incrementally during the discovery phase.

    Args:
        base_url: The root URL of the site under test.
    """

    SCHEMA_VERSION = SCHEMA_VERSION

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.pages: list[Page] = []
        self.forms: list[Form] = []
        self.nav_edges: list[NavEdge] = []
        self.auth_boundaries: list[str] = []   # URLs that are auth walls
        self.api_endpoints: list[ApiEndpoint] = []
        self.tech_stack: dict[str, bool] = {}  # technology -> detected (True/False)
        # TODO: Implement in Phase 2

    def add_page(self, page: Page) -> None:
        """Add a discovered page (deduplicates by URL)."""
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def add_form(self, form: Form) -> None:
        """Record a discovered form."""
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def add_nav_edge(self, edge: NavEdge) -> None:
        """Record a navigation link between pages."""
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def add_api_endpoint(self, endpoint: ApiEndpoint) -> None:
        """Record a discovered API endpoint (deduplicates by url+method)."""
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def detect_tech(self, signals: dict[str, bool]) -> None:
        """Merge technology detection signals into the tech_stack dict."""
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def save(self, path: Path | str) -> None:
        """Serialise site model to JSON at the given path."""
        # TODO: Implement in Phase 2
        raise NotImplementedError

    @classmethod
    def load(cls, path: Path | str) -> "SiteModel":
        """
        Load a site model from JSON, running schema migrations if needed.

        Args:
            path: Path to site_model.json or site-models/{domain}.json

        Returns:
            Populated SiteModel instance.
        """
        # TODO: Implement in Phase 2
        raise NotImplementedError

    def coverage_gaps(self, tested_urls: list[str]) -> list[str]:
        """
        Return page URLs present in the site model but absent from tested_urls.
        Used by the orchestrator to identify untested pages.

        Args:
            tested_urls: List of URLs that have been tested so far.

        Returns:
            List of untested page URLs.
        """
        # TODO: Implement in Phase 2
        raise NotImplementedError
