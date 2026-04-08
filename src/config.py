"""
Configuration loader for qa-auto.yaml.

Loads and validates the YAML config file. Supports environment variable
substitution in values using ${VAR_NAME} syntax.

Config search order:
  1. --config flag (explicit path)
  2. ./qa-auto.yaml  (current directory)
  3. Built-in defaults (no file required)

Usage:
    from src.config import Config

    config = Config.load("./qa-auto.yaml")
    print(config.target.url)
    print(config.models.primary)      # "claude-sonnet-4-6"
    print(config.budget.max_per_session)  # 10.00
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# TODO: Implement in Phase 1


class TargetConfig(BaseModel):
    url: str = ""
    prd: str = ""
    auth_cookie: str = ""
    exclude_paths: list[str] = Field(default_factory=list)


class BrowserConfig(BaseModel):
    engine: str = "chromium"          # chromium | firefox | webkit
    headless: bool = True
    viewports: list[str] = Field(default_factory=lambda: ["1920x1080"])


class ModelsConfig(BaseModel):
    primary: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    sub: str = ""                     # defaults to primary if empty


class BudgetConfig(BaseModel):
    max_per_session: float = 10.00    # USD


class GrafanaConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    token: str = ""
    read_only: bool = True


class SentryConfig(BaseModel):
    enabled: bool = False
    org: str = ""
    project: str = ""


class RetryConfig(BaseModel):
    max_attempts_per_agent: int = 3        # hard cap per sub-agent across the session
    max_total_retries_per_session: int = 5 # cap on total retries (attempts > 1) session-wide


class ReportingConfig(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["json", "markdown"])


class Config(BaseModel):
    """Full configuration model for qa-auto.yaml."""

    target: TargetConfig = Field(default_factory=TargetConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    grafana: GrafanaConfig = Field(default_factory=GrafanaConfig)
    sentry: SentryConfig = Field(default_factory=SentryConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """
        Load config from YAML file with environment variable substitution.

        Args:
            path: Path to qa-auto.yaml. If None, searches ./qa-auto.yaml.
                  If no file found, returns Config with defaults.

        Returns:
            Validated Config instance.
        """
        # TODO: Implement in Phase 1
        if path is None:
            candidate = Path("qa-auto.yaml")
            if not candidate.exists():
                return cls()           # all defaults — fine for Phase 0
            path = candidate

        raw = Path(path).read_text()
        raw = _substitute_env_vars(raw)
        data = yaml.safe_load(raw) or {}
        return cls(**data)

    @classmethod
    def defaults(cls) -> "Config":
        """Return a Config with all defaults."""
        return cls()


def _substitute_env_vars(text: str) -> str:
    """
    Replace ${VAR_NAME} patterns with environment variable values.

    Args:
        text: Raw YAML string possibly containing ${VAR} references.

    Returns:
        String with all resolvable ${VAR} patterns replaced.
        Unresolvable vars are left as-is (logged as warnings in Phase 1).
    """
    # TODO: Implement full substitution with warning on missing vars in Phase 1
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", replacer, text)
