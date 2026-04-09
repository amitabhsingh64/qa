"""
Core agentic loop using the AWS Bedrock Converse API (boto3).

Two-phase orchestration:
  Phase 1 — Discovery: Orchestrator invokes the Crawler to map the site.
  Phase 2 — Test + Report: Orchestrator invokes TestGen → Verifier → ReportGen.

The orchestrator has exactly one tool: invoke_agent(agent_id, mission_brief).
It never touches Playwright directly. Each sub-agent runs in its own fresh
Bedrock Converse session with only the tools its manifest declares.

invoke_agent flow:
  1. Our code intercepts the invoke_agent tool call.
  2. Loads agents/{agent_id}/skills.md as the sub-agent system prompt.
  3. Loads agents/{agent_id}/manifest.json to get requires_tools.
  4. Filters the MCP tool list to only those tools.
  5. Runs a fresh inner Bedrock loop (up to SUB_AGENT_MAX_ITER iterations).
  6. Returns the sub-agent's final output as a toolResult to the orchestrator.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from src.config import RetryConfig
from src.prompts import build_orchestrator_prompt
from src.token_usage import TokenUsage
from src.tools import execute_tool_call, mcp_tools_to_bedrock

AGENTS_DIR = Path(__file__).parent.parent / "agents"

_DEFAULT_MAX_ITER = 25  # fallback if manifest is missing max_iterations

# Module-level agent cache: {agent_id: {"skills": str, "manifest": dict}}
# Loaded once per session; call clear_cache() between sessions or during development.
_agent_cache: dict[str, dict] = {}


def clear_cache() -> None:
    """Clear the agent manifest + skills cache. Call between sessions or during dev."""
    _agent_cache.clear()

# ---------------------------------------------------------------------------
# Retry-scope helpers
# ---------------------------------------------------------------------------

def _retry_reason(prev_status: str) -> str:
    """Map the previous invocation's status to a retry reason string."""
    if prev_status == "capped":
        return "previous_attempt_capped"
    if prev_status in ("error", "running"):
        return "previous_attempt_errored"
    return "explicit_orchestrator_decision"


def _parse_retry_context(mission_brief: str) -> list[str]:
    """
    Extract the bulleted items list from a '## Retry context' section.

    The orchestrator writes this section when retrying a sub-agent. Only
    bullet items that are not the 'Previous invocation' metadata line or
    a 'Note:' line are returned as items_targeted.

    Returns [] if no section is found.
    """
    match = re.search(
        r"##\s+Retry\s+context\b.*?\n(.*?)(?=\n##\s|\Z)",
        mission_brief,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return []
    block = match.group(1)
    items = re.findall(r"^\s*[-*]\s+(.+)", block, re.MULTILINE)
    return [
        item.strip()
        for item in items
        if not re.match(r"(?i)(previous invocation|note:)", item.strip())
    ]


def _compute_retry_counts(
    agent_id: str,
    items_targeted: list[str],
    output_text: str,
) -> tuple[int | None, int | None]:
    """
    Try to count how many of items_targeted appear in the retry output.

    Verifier: items_targeted are finding IDs → matched against verdict finding_id.
    Crawler:  items_targeted are page URLs    → matched against pages[].url.
    Others:   free-text targets, not reliably matchable → returns (None, None).

    Returns (items_completed, items_still_missing).
    """
    if not items_targeted:
        return None, None

    clean = output_text.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(
            lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        )

    try:
        parsed = json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        return None, None

    targeted_lower = [t.lower().strip() for t in items_targeted]

    if agent_id == "verifier":
        verdicts = (
            parsed.get("verdicts")
            or parsed.get("completed", {}).get("verdicts", [])
            or []
        )
        classified = {v.get("finding_id", "").lower() for v in verdicts}
        completed = sum(1 for t in targeted_lower if t in classified)
        return completed, len(targeted_lower) - completed

    if agent_id == "crawler":
        pages = (
            parsed.get("pages")
            or parsed.get("completed", {}).get("pages", [])
            or []
        )
        crawled = {p.get("url", "").lower() for p in pages}
        completed = sum(1 for t in targeted_lower if t in crawled)
        return completed, len(targeted_lower) - completed

    # TestGen and ReportGen: items are free-text, not reliably matchable
    return None, None


# The single tool the orchestrator can call
INVOKE_AGENT_TOOL = {
    "toolSpec": {
        "name": "invoke_agent",
        "description": (
            "Delegate a task to a specialist sub-agent. The sub-agent runs in its "
            "own isolated context with only the tools it needs. Returns the sub-agent's "
            "structured JSON output as a string."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "enum": ["crawler", "test_generator", "verifier", "report_generator"],
                        "description": "Which sub-agent to invoke.",
                    },
                    "mission_brief": {
                        "type": "string",
                        "description": (
                            "Full context and task for the sub-agent. Include: "
                            "target URL, all relevant data from prior agents, "
                            "specific instructions, and expected output format."
                        ),
                    },
                },
                "required": ["agent_id", "mission_brief"],
            }
        },
    }
}


async def run_qa_loop(
    url: str,
    prd_content: str,
    mcp_session,
    bedrock_client,
    model_name: str,
    sub_model_name: str,
    token_usage: TokenUsage,
    retry_config: RetryConfig | None = None,
    verbose: bool = True,
) -> tuple[str, list[dict], dict[str, str]]:
    """
    Run the two-phase QA orchestration loop.

    Phase 1: Orchestrator invokes Crawler → site_map
    Phase 2: Orchestrator invokes TestGen → Verifier → ReportGen

    Returns:
        Tuple of (final_text, conversation_log, sub_agent_results).
        sub_agent_results keys: "crawler", "test_generator", "verifier", "report_generator"
    """
    # Clear the agent cache at session start so skills.md edits take effect
    # without restarting the process (important during development)
    clear_cache()

    if retry_config is None:
        retry_config = RetryConfig()

    tools_response = await mcp_session.list_tools()
    all_mcp_tools = mcp_tools_to_bedrock(tools_response.tools)

    if verbose:
        print(f"  Playwright MCP: {len(all_mcp_tools)} tools available")
        print(f"  Orchestrator   : {model_name}")
        print(f"  Sub-agents     : {sub_model_name}")
        print()

    orchestrator_skills = _load_skills("orchestrator")
    orchestrator_manifest = _load_agent("orchestrator")["manifest"]
    orchestrator_max_iter = orchestrator_manifest.get("max_iterations", _DEFAULT_MAX_ITER)
    orchestrator_max_tokens = orchestrator_manifest.get("max_output_tokens", 16384)
    initial_message = build_orchestrator_prompt(url, prd_content)

    messages: list[dict] = [
        {"role": "user", "content": [{"text": initial_message}]}
    ]
    conversation_log: list[dict] = [
        {"role": "user", "content": initial_message, "iteration": 0}
    ]
    sub_agent_results: dict[str, str] = {}
    final_text = ""

    for iteration in range(1, orchestrator_max_iter + 1):
        if verbose:
            print(f"[orchestrator iter {iteration:02d}]", end=" ", flush=True)

        response = bedrock_client.converse(
            modelId=model_name,
            system=[{"text": orchestrator_skills}],
            messages=messages,
            inferenceConfig={"maxTokens": orchestrator_max_tokens, "temperature": 1.0},
            toolConfig={"tools": [INVOKE_AGENT_TOOL]},
        )

        token_usage.add(response.get("usage"), agent_id="orchestrator")

        stop_reason = response.get("stopReason", "")
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        text_parts: list[str] = []
        tool_use_blocks: list[dict] = []
        for block in assistant_message.get("content", []):
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tool_use_blocks.append(block["toolUse"])

        text_content = "\n".join(text_parts)

        if verbose:
            tools_str = ", ".join(
                f"{t['name']}({t['input'].get('agent_id', '')})" for t in tool_use_blocks
            ) if tool_use_blocks else "no tool calls"
            print(f"stop={stop_reason} [{tools_str}]")
            if text_content:
                print(f"  {text_content[:200].replace(chr(10), ' ')}")

        conversation_log.append({
            "role": "orchestrator",
            "iteration": iteration,
            "text": text_content[:500],
            "tool_calls": [
                {"id": t["toolUseId"], "name": t["name"], "args": t["input"]}
                for t in tool_use_blocks
            ],
            "stop_reason": stop_reason,
        })

        if stop_reason == "end_turn" and not tool_use_blocks:
            final_text = text_content
            break

        if stop_reason == "max_tokens":
            # Orchestrator ran out of output tokens mid-response.
            # Any tool calls in this message are incomplete — Bedrock may have
            # truncated the tool input JSON, so required fields may be missing.
            # Feed back an error so the orchestrator can retry with a shorter brief.
            if verbose:
                print(
                    f"\n  WARNING: orchestrator hit max_tokens at iteration {iteration}. "
                    f"Tool input may be truncated. Feeding error back.\n"
                )
            error_blocks: list[dict] = []
            for tool_use in tool_use_blocks:
                error_blocks.append({
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": json.dumps({
                            "status": "error",
                            "error": "orchestrator_max_tokens",
                            "message": (
                                "Your response was cut off because it exceeded the output "
                                "token limit. The mission_brief you were writing is too long. "
                                "Retry with a shorter brief: summarise the input data instead "
                                "of copying it verbatim, or split into multiple invoke_agent calls."
                            ),
                        })}],
                        "status": "error",
                    }
                })
            if error_blocks:
                messages.append({"role": "user", "content": error_blocks})
                continue
            # No tool calls at all — treat as end of turn
            final_text = text_content
            break

        if not tool_use_blocks:
            final_text = text_content
            break

        # Handle invoke_agent tool calls
        tool_result_blocks: list[dict] = []
        for tool_use in tool_use_blocks:
            if tool_use["name"] != "invoke_agent":
                result_text = f"[ERROR] Orchestrator called unexpected tool '{tool_use['name']}'. Only invoke_agent is allowed."
            else:
                agent_id = tool_use["input"].get("agent_id", "")
                mission_brief = tool_use["input"].get("mission_brief", "")
                if not agent_id or not mission_brief:
                    result_text = json.dumps({
                        "status": "error",
                        "error": "malformed_tool_input",
                        "message": (
                            "invoke_agent call is missing required fields. "
                            f"Got keys: {list(tool_use['input'].keys())}. "
                            "Both 'agent_id' and 'mission_brief' are required."
                        ),
                    })
                    conversation_log.append({
                        "role": "sub_agent_result",
                        "agent_id": agent_id or "unknown",
                        "result_preview": result_text,
                    })
                    tool_result_blocks.append({
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"text": result_text}],
                        }
                    })
                    continue

                # ----------------------------------------------------------
                # Retry budget enforcement
                # ----------------------------------------------------------
                prior_invocations = token_usage.get_invocations(agent_id)
                attempt = len(prior_invocations) + 1
                total_retries = sum(
                    1 for inv in token_usage.get_invocations()
                    if inv["attempt"] > 1
                )

                if attempt > retry_config.max_attempts_per_agent:
                    result_text = json.dumps({
                        "status": "error",
                        "error": "retry_budget_exceeded",
                        "message": (
                            f"Agent {agent_id} has been invoked {len(prior_invocations)} "
                            f"time(s), which is the per-agent limit of "
                            f"{retry_config.max_attempts_per_agent}."
                        ),
                        "agent_id": agent_id,
                    })
                    if verbose:
                        print(f"\n  ✗ [{agent_id}] retry budget exceeded (attempt {attempt} > {retry_config.max_attempts_per_agent})\n")
                elif attempt > 1 and total_retries >= retry_config.max_total_retries_per_session:
                    result_text = json.dumps({
                        "status": "error",
                        "error": "session_retry_budget_exceeded",
                        "message": (
                            f"Session has used {total_retries} retry/retries, which is "
                            f"the session limit of {retry_config.max_total_retries_per_session}."
                        ),
                    })
                    if verbose:
                        print(f"\n  ✗ [{agent_id}] session retry budget exceeded ({total_retries} retries used)\n")
                else:
                    previous_inv_id = (
                        prior_invocations[-1]["invocation_id"]
                        if prior_invocations else None
                    )

                    # Build retry_scope for retried invocations
                    retry_scope: dict | None = None
                    if attempt > 1 and prior_invocations:
                        prev_status = prior_invocations[-1].get("status", "")
                        retry_scope = {
                            "reason": _retry_reason(prev_status),
                            "items_targeted": _parse_retry_context(mission_brief),
                            "items_completed": None,
                            "items_still_missing": None,
                        }

                    if verbose:
                        attempt_label = f" (attempt {attempt})" if attempt > 1 else ""
                        print(f"\n  → [{agent_id}] starting{attempt_label}...")

                    result_text = await run_sub_agent(
                        agent_id=agent_id,
                        mission_brief=mission_brief,
                        all_mcp_tools=all_mcp_tools,
                        mcp_session=mcp_session,
                        bedrock_client=bedrock_client,
                        model_name=sub_model_name,
                        token_usage=token_usage,
                        attempt=attempt,
                        previous_invocation_id=previous_inv_id,
                        retry_scope=retry_scope,
                        verbose=verbose,
                    )

                    sub_agent_results[agent_id] = result_text

                    # After verifier completes, append the invocation telemetry
                    # snapshot to the tool result so the orchestrator has it
                    # available when composing the report_generator mission brief.
                    if agent_id == "verifier":
                        telemetry_note = (
                            "\n\n---\n"
                            "## Session telemetry (for report_generator mission brief)\n\n"
                            "Include the following two fields verbatim when writing "
                            "the report_generator mission brief.\n\n"
                            "### Agent Invocations\n"
                            f"```json\n{json.dumps(token_usage.get_invocations(), indent=2)}\n```\n\n"
                            "### Retry Summary\n"
                            f"```json\n{json.dumps(token_usage.compute_retry_summary(), indent=2)}\n```"
                        )
                        result_text = result_text + telemetry_note

                    if verbose:
                        print(f"  ← [{agent_id}] done ({len(result_text)} chars)\n")

                conversation_log.append({
                    "role": "sub_agent_result",
                    "agent_id": agent_id,
                    "result_preview": result_text[:500],
                })

            tool_result_blocks.append({
                "toolResult": {
                    "toolUseId": tool_use["toolUseId"],
                    "content": [{"text": result_text}],
                }
            })

        messages.append({"role": "user", "content": tool_result_blocks})

    # The report is in sub_agent_results; orchestrator's final text is just a summary
    return final_text, conversation_log, sub_agent_results


async def run_sub_agent(
    agent_id: str,
    mission_brief: str,
    all_mcp_tools: list[dict],
    mcp_session,
    bedrock_client,
    model_name: str,
    token_usage: TokenUsage,
    attempt: int = 1,
    previous_invocation_id: str | None = None,
    retry_scope: dict | None = None,
    verbose: bool = True,
) -> str:
    """
    Run a sub-agent in a fresh Bedrock Converse session.

    The sub-agent receives:
    - Its skills.md as the system prompt
    - Only the tools in its manifest.json requires_tools
    - The mission_brief as the initial user message

    Returns the sub-agent's final text output (structured JSON expected).
    """
    agent_data      = _load_agent(agent_id)
    skills          = agent_data["skills"]
    manifest        = agent_data["manifest"]
    max_iter        = manifest.get("max_iterations", _DEFAULT_MAX_ITER)
    max_out_tokens  = manifest.get("max_output_tokens", 8192)
    agent_tools     = _filter_tools(agent_id, all_mcp_tools)

    messages: list[dict] = [
        {"role": "user", "content": [{"text": mission_brief}]}
    ]

    tool_config     = {"tools": agent_tools} if agent_tools else None
    final_text      = ""
    started_at      = datetime.now(timezone.utc)
    tokens_before   = token_usage.snapshot_tokens(agent_id)
    iterations_used = 0
    inv_status      = "complete"
    capped_summary  = None
    tool_use_blocks: list[dict] = []

    # Open the invocation record before the first LLM call so it is tracked
    # even if the call raises an exception.
    inv_id = token_usage.begin_invocation(
        agent_id=agent_id,
        attempt=attempt,
        previous_invocation_id=previous_invocation_id,
        started_at=started_at,
    )

    try:
        from botocore.exceptions import ReadTimeoutError as BedrockReadTimeout
    except ImportError:
        BedrockReadTimeout = OSError  # fallback — should never happen

    try:
        for iteration in range(1, max_iter + 1):
            iterations_used = iteration
            if verbose:
                print(f"    [{agent_id} {iteration:02d}]", end=" ", flush=True)

            call_kwargs: dict = dict(
                modelId=model_name,
                system=[{"text": skills}],
                messages=messages,
                inferenceConfig={"maxTokens": max_out_tokens, "temperature": 1.0},
            )
            if tool_config:
                call_kwargs["toolConfig"] = tool_config

            response = bedrock_client.converse(**call_kwargs)
            token_usage.add(response.get("usage"), agent_id=agent_id)

            stop_reason = response.get("stopReason", "")
            assistant_message = response["output"]["message"]
            messages.append(assistant_message)

            text_parts: list[str] = []
            tool_use_blocks = []
            for block in assistant_message.get("content", []):
                if "text" in block:
                    text_parts.append(block["text"])
                elif "toolUse" in block:
                    tool_use_blocks.append(block["toolUse"])

            text_content = "\n".join(text_parts)

            if verbose:
                tool_names = ", ".join(t["name"] for t in tool_use_blocks)
                print(f"stop={stop_reason} tools=[{tool_names}]")

            if stop_reason == "end_turn" and not tool_use_blocks:
                final_text = text_content
                inv_status = "complete"
                break

            if not tool_use_blocks:
                final_text = text_content
                inv_status = "complete"
                break

            # Execute tools and feed results back for the next iteration
            tool_result_blocks: list[dict] = []
            for tool_use in tool_use_blocks:
                result_text = await execute_tool_call(
                    mcp_session, tool_use["name"], tool_use["input"]
                )
                if verbose:
                    preview = result_text[:120].replace("\n", " ")
                    print(f"      {tool_use['name']}: {preview}")

                tool_result_blocks.append({
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"text": result_text}],
                    }
                })

            messages.append({"role": "user", "content": tool_result_blocks})
        else:
            # for...else fires when the loop exhausted all iterations without a break.
            inv_status = "capped"
            print(
                f"\n  WARNING: {agent_id} hit its {max_iter}-iteration cap. "
                f"Requesting best-effort summary of partial work..."
            )
            final_text, capped_summary = await _request_cap_summary(
                agent_id=agent_id,
                skills=skills,
                messages=messages,
                last_tool_use_blocks=tool_use_blocks,
                bedrock_client=bedrock_client,
                model_name=model_name,
                token_usage=token_usage,
                max_output_tokens=max_out_tokens,
                tool_config=tool_config,
            )
    except BedrockReadTimeout as exc:
        inv_status = "error"
        print(
            f"\n  ERROR: [{agent_id}] Bedrock read timeout after {iterations_used} iterations. "
            f"Returning error result to orchestrator. ({exc})"
        )
        final_text = json.dumps({
            "status": "error",
            "error": "bedrock_read_timeout",
            "message": (
                f"Bedrock read timed out during iteration {iterations_used}. "
                "The model may have been generating a very long response."
            ),
            "agent_id": agent_id,
            "iterations_completed": iterations_used,
        })
    except Exception:
        inv_status = "error"
        raise
    else:
        # Compute retry counts now that we have final_text (only runs if no exception)
        if retry_scope and retry_scope.get("items_targeted"):
            completed, missing = _compute_retry_counts(
                agent_id, retry_scope["items_targeted"], final_text
            )
            retry_scope["items_completed"] = completed
            retry_scope["items_still_missing"] = missing
    finally:
        token_usage.close_invocation(
            inv_id=inv_id,
            status=inv_status,
            iterations_used=iterations_used,
            iterations_limit=max_iter,
            started_at=started_at,
            tokens_before=tokens_before,
            capped_summary=capped_summary,
            retry_scope=retry_scope,
        )

    return final_text


_CAP_FALLBACK_SUMMARY = {
    "in_progress": "unknown — agent did not produce a valid summary",
    "narrative": "Agent reached iteration limit and could not produce a summary.",
}


async def _request_cap_summary(
    agent_id: str,
    skills: str,
    messages: list[dict],
    last_tool_use_blocks: list[dict],
    bedrock_client,
    model_name: str,
    token_usage: TokenUsage,
    max_output_tokens: int = 8192,
    tool_config: dict | None = None,
) -> tuple[str, dict]:
    """
    Called when a sub-agent hits its iteration cap.

    Appends a final user message instructing the agent to produce a structured
    summary of partial work, makes one no-tool Bedrock call, then parses the
    response as JSON.

    Returns:
        (output_str, capped_summary) where:
        - output_str: JSON string to return to the orchestrator as the agent's output
        - capped_summary: metadata dict for the invocation record
    """
    in_progress_tools = (
        ", ".join(t["name"] for t in last_tool_use_blocks)
        if last_tool_use_blocks
        else "unknown"
    )

    cap_prompt = (
        "You have reached your iteration limit. Stop immediately — do not call any tools.\n\n"
        f"You were last attempting: {in_progress_tools}\n\n"
        "Produce a JSON summary of your partial work. Your response must be a single "
        "valid JSON object with exactly these fields:\n\n"
        "{\n"
        '  "status": "capped",\n'
        '  "completed": { ... your normal output schema with only what you fully finished ... },\n'
        '  "in_progress": { "description": "what you were doing when stopped" },\n'
        '  "skipped": ["item from mission brief never addressed", ...],\n'
        '  "narrative": "2-3 sentences in plain English explaining what happened"\n'
        "}\n\n"
        "Output only the JSON object. No prose, no markdown fences, no tool calls."
    )

    summary_messages = messages + [
        {"role": "user", "content": [{"text": cap_prompt}]}
    ]

    cap_call_kwargs: dict = dict(
        modelId=model_name,
        system=[{"text": skills}],
        messages=summary_messages,
        inferenceConfig={"maxTokens": max_output_tokens, "temperature": 0.0},
    )
    # Bedrock requires toolConfig whenever any message in the history contains
    # toolUse or toolResult blocks — pass it through even though the cap prompt
    # instructs the model not to call any tools.
    if tool_config:
        cap_call_kwargs["toolConfig"] = tool_config

    response = bedrock_client.converse(**cap_call_kwargs)
    token_usage.add(response.get("usage"), agent_id=agent_id)

    raw = ""
    for block in response["output"]["message"].get("content", []):
        if "text" in block:
            raw += block["text"]

    # Strip markdown fences if the model wrapped the JSON anyway
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )

    try:
        parsed = json.loads(clean)
        parsed["status"] = "capped"  # enforce — agent may have omitted it

        completed = parsed.get("completed", {})
        skipped   = parsed.get("skipped", [])

        # completed_count: find the first list value in completed, else count keys
        completed_count = 0
        for v in completed.values() if isinstance(completed, dict) else []:
            if isinstance(v, list):
                completed_count = len(v)
                break
        if completed_count == 0 and isinstance(completed, dict):
            completed_count = len(completed)

        capped_summary = {
            "completed_count": completed_count,
            "skipped_count":   len(skipped) if isinstance(skipped, list) else 0,
            "in_progress":     parsed.get("in_progress", {}).get("description", "unknown"),
            "narrative":       parsed.get("narrative", ""),
        }

        return json.dumps(parsed), capped_summary

    except (json.JSONDecodeError, Exception) as exc:
        print(f"  WARNING: {agent_id} cap summary JSON parse failed ({exc}). Using fallback.")

        fallback = {
            "status":      "capped",
            "completed":   {},
            "in_progress": {"description": "unknown — agent did not produce a valid summary"},
            "skipped":     [],
            "narrative":   "Agent reached iteration limit and could not produce a summary.",
        }
        capped_summary = {
            "completed_count": 0,
            "skipped_count":   0,
            "in_progress":     _CAP_FALLBACK_SUMMARY["in_progress"],
            "narrative":       _CAP_FALLBACK_SUMMARY["narrative"],
        }
        return json.dumps(fallback), capped_summary


def _load_agent(agent_id: str) -> dict:
    """
    Load and cache an agent's manifest + skills for the current session.

    Returns a dict with keys "skills" (str) and "manifest" (dict).
    Cached in _agent_cache after first load — call clear_cache() to reset.
    """
    if agent_id in _agent_cache:
        return _agent_cache[agent_id]

    skills_path = AGENTS_DIR / agent_id / "skills.md"
    manifest_path = AGENTS_DIR / agent_id / "manifest.json"

    if not skills_path.exists():
        raise FileNotFoundError(
            f"No skills.md found for agent '{agent_id}' at {skills_path}"
        )
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest.json found for agent '{agent_id}' at {manifest_path}"
        )

    entry = {
        "skills": skills_path.read_text(encoding="utf-8"),
        "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
    }
    _agent_cache[agent_id] = entry
    return entry


def _load_skills(agent_id: str) -> str:
    return _load_agent(agent_id)["skills"]


def _filter_tools(agent_id: str, all_tools: list[dict]) -> list[dict]:
    """
    Return only the MCP tools declared in the agent's manifest requires_tools.
    Returns empty list if requires_tools is absent or empty (no-tool agent).
    Tool list is already in Bedrock format — filter on toolSpec.name.
    """
    required = set(_load_agent(agent_id)["manifest"].get("requires_tools", []))
    if not required:
        return []
    return [t for t in all_tools if t["toolSpec"]["name"] in required]
