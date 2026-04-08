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
from pathlib import Path

from src.prompts import build_orchestrator_prompt
from src.token_usage import TokenUsage
from src.tools import execute_tool_call, mcp_tools_to_bedrock

AGENTS_DIR = Path(__file__).parent.parent / "agents"

ORCHESTRATOR_MAX_ITER = 20
SUB_AGENT_MAX_ITER = 25  # hard cap — hitting this means skills.md needs attention

# Module-level agent cache: {agent_id: {"skills": str, "manifest": dict}}
# Loaded once per session; call clear_cache() between sessions or during development.
_agent_cache: dict[str, dict] = {}


def clear_cache() -> None:
    """Clear the agent manifest + skills cache. Call between sessions or during dev."""
    _agent_cache.clear()

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
    token_usage: TokenUsage,
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

    tools_response = await mcp_session.list_tools()
    all_mcp_tools = mcp_tools_to_bedrock(tools_response.tools)

    if verbose:
        print(f"  Playwright MCP: {len(all_mcp_tools)} tools available")
        print()

    orchestrator_skills = _load_skills("orchestrator")
    initial_message = build_orchestrator_prompt(url, prd_content)

    messages: list[dict] = [
        {"role": "user", "content": [{"text": initial_message}]}
    ]
    conversation_log: list[dict] = [
        {"role": "user", "content": initial_message, "iteration": 0}
    ]
    sub_agent_results: dict[str, str] = {}
    final_text = ""

    for iteration in range(1, ORCHESTRATOR_MAX_ITER + 1):
        if verbose:
            print(f"[orchestrator iter {iteration:02d}]", end=" ", flush=True)

        response = bedrock_client.converse(
            modelId=model_name,
            system=[{"text": orchestrator_skills}],
            messages=messages,
            inferenceConfig={"maxTokens": 4096, "temperature": 1.0},
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

        if not tool_use_blocks:
            final_text = text_content
            break

        # Handle invoke_agent tool calls
        tool_result_blocks: list[dict] = []
        for tool_use in tool_use_blocks:
            if tool_use["name"] != "invoke_agent":
                result_text = f"[ERROR] Orchestrator called unexpected tool '{tool_use['name']}'. Only invoke_agent is allowed."
            else:
                agent_id = tool_use["input"]["agent_id"]
                mission_brief = tool_use["input"]["mission_brief"]

                if verbose:
                    print(f"\n  → [{agent_id}] starting...")

                result_text = await run_sub_agent(
                    agent_id=agent_id,
                    mission_brief=mission_brief,
                    all_mcp_tools=all_mcp_tools,
                    mcp_session=mcp_session,
                    bedrock_client=bedrock_client,
                    model_name=model_name,
                    token_usage=token_usage,
                    verbose=verbose,
                )

                sub_agent_results[agent_id] = result_text

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
    skills = _load_skills(agent_id)
    agent_tools = _filter_tools(agent_id, all_mcp_tools)

    messages: list[dict] = [
        {"role": "user", "content": [{"text": mission_brief}]}
    ]

    tool_config = {"tools": agent_tools} if agent_tools else None
    final_text = ""

    for iteration in range(1, SUB_AGENT_MAX_ITER + 1):
        if verbose:
            print(f"    [{agent_id} {iteration:02d}]", end=" ", flush=True)

        call_kwargs: dict = dict(
            modelId=model_name,
            system=[{"text": skills}],
            messages=messages,
            inferenceConfig={"maxTokens": 8192, "temperature": 1.0},
        )
        if tool_config:
            call_kwargs["toolConfig"] = tool_config

        response = bedrock_client.converse(**call_kwargs)
        token_usage.add(response.get("usage"), agent_id=agent_id)

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
            tool_names = ", ".join(t["name"] for t in tool_use_blocks)
            print(f"stop={stop_reason} tools=[{tool_names}]")

        if stop_reason == "end_turn" and not tool_use_blocks:
            final_text = text_content
            break

        if not tool_use_blocks:
            final_text = text_content
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
        # for...else: loop completed all iterations without a break (cap hit)
        print(
            f"\n  WARNING: {agent_id} hit the {SUB_AGENT_MAX_ITER}-iteration cap. "
            f"Review its skills.md — it may be looping or not terminating cleanly."
        )

    return final_text


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
