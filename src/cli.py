"""
CLI entry point: qa-auto <url> [options]

Usage:
    qa-auto https://staging.myapp.com
    qa-auto https://staging.myapp.com --prd ./requirements.md
    qa-auto https://staging.myapp.com --browser firefox --no-headless
    qa-auto https://staging.myapp.com --budget 5.00 --output ./runs/

Options:
    url                      Target URL to test (required)
    --prd PATH               Path to PRD/requirements file for context
    --auth-cookie COOKIE     Session cookie for authenticated testing
    --browser ENGINE         Browser engine: chromium | firefox | webkit (default: chromium)
    --headless / --no-headless  Run browser headlessly (default: headless)
    --budget FLOAT           Max spend in USD for this session (default: 10.00)
    --output DIR             Output directory for reports (default: ./sessions/)
    --config PATH            Path to qa-auto.yaml (default: ./qa-auto.yaml)
    --model MODEL            Override Claude model (e.g. claude-opus-4-6, claude-sonnet-4-6)
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()  # loads .env from cwd (or any parent) before anything else runs


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for qa-auto."""
    parser = argparse.ArgumentParser(
        prog="qa-auto",
        description="AI-powered, multi-agent website QA testing system.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "url",
        help="Target URL to test (e.g. https://staging.myapp.com)",
    )
    parser.add_argument(
        "--prd",
        metavar="PATH",
        default=None,
        help="Path to PRD or requirements markdown file",
    )
    parser.add_argument(
        "--auth-cookie",
        metavar="COOKIE",
        default=None,
        help="Session cookie string for authenticated testing",
    )
    parser.add_argument(
        "--browser",
        choices=["chromium", "firefox", "webkit"],
        default="chromium",
        help="Browser engine (default: chromium)",
    )
    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default)",
    )
    headless_group.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run browser with visible window",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        metavar="USD",
        help="Maximum spend in USD for this session (default: from config or 10.00)",
    )
    parser.add_argument(
        "--output",
        metavar="DIR",
        default="./sessions/",
        help="Output directory for session artifacts (default: ./sessions/)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to qa-auto.yaml config file",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        default=None,
        help="Override Claude model (e.g. claude-opus-4-6, claude-sonnet-4-6)",
    )

    return parser


def main() -> None:
    """
    CLI entry point. Wired to `qa-auto` script via pyproject.toml.

    Phase 0: delegates to phase0.py's main().
    Phase 1+: loads config, initialises full agent infrastructure.
    """
    # TODO: Implement in Phase 1 — wire up full agent runner
    # For now, delegate to phase0 as the functional proof of concept.

    parser = build_parser()
    args = parser.parse_args()

    import asyncio
    from src.main import main as qa_main

    asyncio.run(
        qa_main(
            url=args.url,
            prd_path=args.prd,
            headless=args.headless,
            output_dir=args.output,
            model=args.model,
        )
    )


if __name__ == "__main__":
    main()
