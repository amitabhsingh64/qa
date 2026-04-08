"""
QA report generation.

Two responsibilities:
  1. Parse the structured JSON findings block from the model's final output.
  2. Render a human-readable markdown report from the parsed findings.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from src.token_usage import TokenUsage


# ---------------------------------------------------------------------------
# Findings parser
# ---------------------------------------------------------------------------

def extract_findings_from_text(text: str) -> dict:
    """
    Parse the structured JSON findings block from the model's final output.

    The model is instructed to emit a ```json ... ``` fenced block. Falls back
    to bare JSON extraction, then to an empty findings skeleton.

    Args:
        text: Full text of the model's final response.

    Returns:
        Parsed findings dict with keys: summary, findings, pages_tested.
    """
    # Primary: fenced ```json ... ``` block
    match = re.search(r"```json\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Fallback: first { … last }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

    return {
        "summary": {
            "pages_visited": 0,
            "tests_executed": 0,
            "issues_found": 0,
            "tech_stack": [],
            "note": "Could not parse structured findings from model output",
        },
        "findings": [],
        "pages_tested": [],
    }


# ---------------------------------------------------------------------------
# Markdown report renderer
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def generate_markdown_report(
    url: str,
    start_time: datetime,
    end_time: datetime,
    model_name: str,
    findings_data: dict,
    token_usage: TokenUsage,
    prd_path: str | None,
) -> str:
    """
    Render a formatted markdown QA report.

    Args:
        url:           Target URL that was tested.
        start_time:    Session start datetime (UTC).
        end_time:      Session end datetime (UTC).
        model_name:    Claude model used.
        findings_data: Parsed findings dict from ``extract_findings_from_text``.
        token_usage:   Accumulated token usage for the session.
        prd_path:      Optional path to the PRD file that was provided.

    Returns:
        Formatted markdown string.
    """
    duration = end_time - start_time
    mins, secs = divmod(int(duration.total_seconds()), 60)
    duration_str = f"{mins}m {secs}s"

    summary = findings_data.get("summary", {})
    findings = findings_data.get("findings", [])
    pages_tested = findings_data.get("pages_tested", [])

    pages_visited = summary.get("pages_visited", len(pages_tested))
    tests_executed = summary.get("tests_executed", 0)
    issues_found = summary.get("issues_found", len(findings))
    tech_stack = summary.get("tech_stack", [])

    severity_counts: dict[str, int] = {k: 0 for k in _SEVERITY_ORDER}
    for f in findings:
        sev = f.get("severity", "info").lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    severity_summary = (
        ", ".join(f"{v} {k}" for k, v in severity_counts.items() if v > 0) or "none"
    )

    lines: list[str] = [
        f"# QA Report — {url}",
        "",
        f"**Date:** {start_time.strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**Duration:** {duration_str}  ",
        f"**Model:** {model_name}  ",
        f"**PRD:** {prd_path or 'not provided'}  ",
        "",
        "## Summary",
        "",
        f"- **Pages visited:** {pages_visited}",
        f"- **Tests executed:** {tests_executed}",
        f"- **Issues found:** {issues_found} ({severity_summary})",
        f"- **Estimated cost:** ${token_usage.estimated_cost_usd:.6f}",
        f"- **Tech stack detected:** {', '.join(tech_stack) if tech_stack else 'unknown'}",
        "",
    ]

    # Issues section
    lines.append("## Issues Found")
    lines.append("")
    if findings:
        sorted_findings = sorted(
            findings,
            key=lambda f: _SEVERITY_ORDER.get(f.get("severity", "info").lower(), 5),
        )
        for finding in sorted_findings:
            sev = finding.get("severity", "info").upper()
            fid = finding.get("id", "")
            title = finding.get("title", "Untitled finding")
            lines.append(f"### [{sev}] {fid} — {title}")
            lines.append("")

            if category := finding.get("category", ""):
                lines.append(f"**Category:** {category}  ")
            if found_url := finding.get("url", ""):
                lines.append(f"**URL:** {found_url}  ")
            if description := finding.get("description", ""):
                lines.append("")
                lines.append(description)

            expected = finding.get("expected", "")
            actual = finding.get("actual", "")
            if expected or actual:
                lines.append("")
                if expected:
                    lines.append(f"**Expected:** {expected}  ")
                if actual:
                    lines.append(f"**Actual:** {actual}  ")

            if steps := finding.get("reproduction_steps", []):
                lines.append("")
                lines.append("**Reproduction steps:**")
                for i, step in enumerate(steps, 1):
                    lines.append(f"{i}. {step}")

            lines.append("")
    else:
        lines.append("No issues found during this session.")
        lines.append("")

    # Pages tested table
    if pages_tested:
        lines += [
            "## Pages Tested",
            "",
            "| URL | Title | Status | Console Errors |",
            "|-----|-------|--------|----------------|",
        ]
        for page in pages_tested:
            lines.append(
                f"| {page.get('url','')} | {page.get('title','')} "
                f"| {page.get('status','')} | {page.get('console_errors', 0)} |"
            )
        lines.append("")

    # Cost breakdown
    lines += [
        "## Cost Breakdown",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Input tokens | {token_usage.input_tokens:,} |",
        f"| Output tokens | {token_usage.output_tokens:,} |",
        f"| Total tokens | {token_usage.total_tokens:,} |",
        f"| Estimated cost | ${token_usage.estimated_cost_usd:.6f} |",
        f"| Model | {model_name} |",
        "",
        "---",
        "",
        f"*Generated by autonomous-qa — {end_time.strftime('%Y-%m-%d')}*",
    ]

    return "\n".join(lines)
