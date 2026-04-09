"""
Session orchestration for qa-auto.

Loads config and environment, launches Playwright MCP, runs the agentic
loop via AWS Bedrock Converse API, parses findings, and writes output files.
This is the async entry point called by ``src/cli.py``.

AWS credentials are resolved by boto3 in the standard order:
  1. Environment variables: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
  2. ~/.aws/credentials profile
  3. IAM instance / task role (EC2 / ECS / Lambda)

Region is read from AWS_DEFAULT_REGION (default: us-east-1).
Model is read from BEDROCK_MODEL env var or --model flag.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MODEL     = "global.anthropic.claude-opus-4-5-20251101-v1:0"
DEFAULT_SUB_MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_REGION    = "us-east-1"
DEFAULT_OUTPUT_DIR = "./sessions/"


async def main(
    url: str,
    prd_path: str | None = None,
    headless: bool = True,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    model: str | None = None,
) -> None:
    """
    Run a full QA session against ``url``.

    Args:
        url:        Target URL to test.
        prd_path:   Optional path to a PRD/requirements file.
        headless:   Run Playwright in headless mode.
        output_dir: Directory to write report, conversation, and cost files.
        model:      Bedrock modelId override (falls back to BEDROCK_MODEL env
                    var, then ``DEFAULT_MODEL``).
    """
    # ------------------------------------------------------------------
    # Resolve model and region
    # ------------------------------------------------------------------
    model_name     = model or os.environ.get("BEDROCK_MODEL", DEFAULT_MODEL)
    sub_model_name = os.environ.get("BEDROCK_SUB_MODEL", DEFAULT_SUB_MODEL)
    region         = os.environ.get("AWS_DEFAULT_REGION", DEFAULT_REGION)

    # ------------------------------------------------------------------
    # Load PRD if provided
    # ------------------------------------------------------------------
    prd_content = ""
    if prd_path:
        prd_file = Path(prd_path)
        if not prd_file.exists():
            print(f"WARNING: PRD file not found: {prd_path}. Continuing without it.")
        else:
            prd_content = prd_file.read_text(encoding="utf-8")
            print(f"Loaded PRD: {prd_path} ({len(prd_content)} chars)")

    # ------------------------------------------------------------------
    # Prepare output directory
    # ------------------------------------------------------------------
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Print session header
    # ------------------------------------------------------------------
    start_time = datetime.now(timezone.utc)
    print()
    print("=" * 60)
    print("  Autonomous QA — AWS Bedrock Converse API")
    print("=" * 60)
    print(f"  Target : {url}")
    print(f"  Model  : {model_name}")
    print(f"  Region : {region}")
    print(f"  PRD    : {prd_path or 'not provided'}")
    print(f"  Mode   : {'headless' if headless else 'visible browser'}")
    print(f"  Output : {out_dir.resolve()}")
    print(f"  Start  : {start_time.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print()

    # ------------------------------------------------------------------
    # Import dependencies (fail fast with clear messages)
    # ------------------------------------------------------------------
    try:
        import boto3 as _boto3
        from botocore.exceptions import NoCredentialsError, ClientError
    except ImportError:
        print(
            "\nERROR: boto3 package not installed.\n"
            "Run: pip install boto3\n",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        print(
            "\nERROR: mcp package not installed.\n"
            "Run: pip install mcp\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Initialise Bedrock client
    # ------------------------------------------------------------------
    from botocore.config import Config as BotocoreConfig
    from src.config import Config
    from src.runner import run_qa_loop
    from src.token_usage import TokenUsage

    session_config = Config.load()

    try:
        bedrock_client = _boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=BotocoreConfig(
                read_timeout=300,   # 5 min — long enough for large model responses
                connect_timeout=10,
                retries={"max_attempts": 8, "mode": "adaptive"},
            ),
        )
    except NoCredentialsError:
        print(
            "\nERROR: No AWS credentials found.\n"
            "Configure via environment variables (AWS_ACCESS_KEY_ID / "
            "AWS_SECRET_ACCESS_KEY) or ~/.aws/credentials.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    token_usage = TokenUsage(model=model_name)

    # ------------------------------------------------------------------
    # Launch Playwright MCP and run the agentic loop
    # ------------------------------------------------------------------
    playwright_args = ["@playwright/mcp@latest"]
    if headless:
        playwright_args.append("--headless")
    playwright_args += ["--timeout", "60000"]  # 60s per browser action (default is 30s)

    server_params = StdioServerParameters(
        command="npx",
        args=playwright_args,
        env=None,
    )

    print("Launching Playwright MCP via npx...")
    print("(First run will download @playwright/mcp if not cached — may take ~30s)")
    print()

    final_text = ""
    conversation_log: list[dict] = []

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                print("Initialising MCP session...")
                await mcp_session.initialize()
                print("MCP session ready.")
                print()

                final_text, conversation_log, sub_agent_results = await run_qa_loop(
                    url=url,
                    prd_content=prd_content,
                    mcp_session=mcp_session,
                    bedrock_client=bedrock_client,
                    model_name=model_name,
                    sub_model_name=sub_model_name,
                    token_usage=token_usage,
                    retry_config=session_config.retry,
                    verbose=True,
                )

    except FileNotFoundError:
        print(
            "\nERROR: 'npx' not found. Node.js must be installed.\n"
            "Install from https://nodejs.org/ then retry.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    except ConnectionError as exc:
        print(
            f"\nERROR: Failed to connect to Playwright MCP: {exc}\n"
            "Ensure @playwright/mcp is accessible via npx.\n"
            "Try: npx @playwright/mcp@latest --headless\n",
            file=sys.stderr,
        )
        sys.exit(1)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        print(
            f"\nERROR: Bedrock API error ({code}): {exc}\n"
            f"Verify the modelId '{model_name}' is enabled in region '{region}'.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    end_time = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Write output files from sub-agent results
    # ------------------------------------------------------------------
    print()
    print("Writing output files...")

    # Sub-agent artifacts
    for agent_id, ext, label in [
        ("crawler",         "site_map.json",   "site_map.json       "),
        ("test_generator",  "findings.json",   "findings.json       "),
        ("verifier",        "verdicts.json",   "verdicts.json       "),
    ]:
        content = sub_agent_results.get(agent_id, "")
        if content:
            path = out_dir / ext
            path.write_text(content, encoding="utf-8")
            print(f"  {label}   -> {path}")

    # ReportGen produces HTML report
    report_html_content = sub_agent_results.get("report_generator", "")
    if report_html_content:
        # Split on marker if agent returned both HTML and markdown
        if "---MARKDOWN---" in report_html_content:
            html_part, md_part = report_html_content.split("---MARKDOWN---", 1)
        else:
            html_part = report_html_content
            md_part = ""

        report_html_path = out_dir / "report.html"
        report_html_path.write_text(html_part.strip(), encoding="utf-8")
        print(f"  report.html          -> {report_html_path}")

        if md_part.strip():
            report_md_path = out_dir / "report.md"
            report_md_path.write_text(md_part.strip(), encoding="utf-8")
            print(f"  report.md            -> {report_md_path}")

    # Parse verdicts for console summary
    verdicts_text = sub_agent_results.get("verifier", "{}")
    try:
        # Strip markdown fences if present
        clean = verdicts_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```", 2)[1]
            if clean.startswith("json"):
                clean = clean[4:]
        verdicts_data = json.loads(clean)
    except (json.JSONDecodeError, IndexError):
        verdicts_data = {}

    findings = verdicts_data.get("findings", [])
    summary = verdicts_data.get("summary", {})

    conversation_path = out_dir / "raw_conversation.json"
    conversation_path.write_text(
        json.dumps(
            {
                "session": {
                    "url": url,
                    "model": model_name,
                    "started_at": start_time.isoformat(),
                    "ended_at": end_time.isoformat(),
                    "prd_path": prd_path,
                    "headless": headless,
                },
                "conversation": conversation_log,
                "final_output": final_text,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"  raw_conversation.json -> {conversation_path}")

    cost_path = out_dir / "cost.json"
    cost_path.write_text(
        json.dumps(
            {
                "session": {
                    "url": url,
                    "model": model_name,
                    "started_at": start_time.isoformat(),
                    "ended_at": end_time.isoformat(),
                    "duration_seconds": (end_time - start_time).total_seconds(),
                },
                "token_usage": token_usage.to_dict(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  cost.json             -> {cost_path}")

    # ------------------------------------------------------------------
    # Final console summary
    # ------------------------------------------------------------------
    duration = end_time - start_time
    mins, secs = divmod(int(duration.total_seconds()), 60)
    duration_str = f"{mins}m {secs}s"

    pages_visited = summary.get("pages_visited", 0)
    issues_found = summary.get("issues_found", len(findings))

    severity_counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        sev = f.get("severity", "info").lower()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    print()
    print("=" * 60)
    print("  SESSION COMPLETE")
    print("=" * 60)
    print(f"  Duration         : {duration_str}")
    print(f"  Pages visited    : {pages_visited}")
    print(f"  Issues found     : {issues_found}")
    for sev in ["critical", "high", "medium", "low", "info"]:
        count = severity_counts.get(sev, 0)
        if count:
            print(f"    {sev:10s}   : {count}")
    print(f"  Input tokens     : {token_usage.input_tokens:,}")
    print(f"  Output tokens    : {token_usage.output_tokens:,}")
    print(f"  Estimated cost   : ${token_usage.estimated_cost_usd:.6f}")
    report_html_path = out_dir / "report.html"
    if report_html_path.exists():
        print(f"  Report           : {report_html_path.resolve()}")
    print("=" * 60)
    print()
