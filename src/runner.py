"""
Core agentic loop using the AWS Bedrock Converse API (boto3).

The loop follows the standard tool-use pattern:
  1. Send messages to Claude-on-Bedrock with available Playwright tools.
  2. If the model returns toolUse blocks, execute them via MCP.
  3. Feed toolResult blocks back in a user turn and repeat.
  4. Stop when stopReason is "end_turn" or the model emits TESTING_COMPLETE.
  5. Run a final summarization call to produce structured JSON findings.

Bedrock Converse message format (differs from the Anthropic SDK):
  - Content is always a list of typed blocks, even for plain text.
  - System prompt is a separate list: [{"text": "..."}]
  - Tool definitions use the toolSpec / inputSchema.json wrapper.
  - Tool results use the toolResult content block type.
  - Usage keys are camelCase: inputTokens / outputTokens.
"""

from __future__ import annotations

import json

from src.prompts import SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT, build_summary_prompt
from src.token_usage import TokenUsage
from src.tools import execute_tool_call, mcp_tools_to_bedrock

MAX_ITERATIONS = 50
_CONTEXT_WINDOW = 20  # keep last N messages beyond the first user message


async def run_qa_loop(
    url: str,
    prd_content: str,
    mcp_session,
    bedrock_client,
    model_name: str,
    token_usage: TokenUsage,
    verbose: bool = True,
) -> tuple[str, list[dict]]:
    """
    Run the QA agentic loop and return the final model output plus a conversation log.

    Args:
        url:            Target URL to test.
        prd_content:    PRD/requirements text (empty string if not provided).
        mcp_session:    Active MCP ``ClientSession`` connected to Playwright.
        bedrock_client: boto3 ``bedrock-runtime`` client.
        model_name:     Bedrock modelId to use.
        token_usage:    TokenUsage accumulator (mutated in place).
        verbose:        Print progress to stdout.

    Returns:
        Tuple of (final_text, conversation_log).
    """
    tools_response = await mcp_session.list_tools()
    bedrock_tools = mcp_tools_to_bedrock(tools_response.tools)

    if verbose:
        tool_names = [t["toolSpec"]["name"] for t in bedrock_tools]
        print(f"  Connected to Playwright MCP: {len(bedrock_tools)} tools available")
        print(f"  Tools: {', '.join(tool_names[:8])}{'...' if len(tool_names) > 8 else ''}")
        print()

    initial_content = (
        f"Test this URL thoroughly: {url}\n\n"
        f"PRD context: {prd_content if prd_content else 'none provided'}\n\n"
        "Use the Playwright tools to explore the site, identify bugs, and test key "
        "user flows. Be systematic: start with discovery, then test each major "
        "feature area. When complete, output your findings JSON followed by TESTING_COMPLETE."
    )

    # Bedrock requires content as a list of typed blocks, even for plain text
    messages: list[dict] = [
        {"role": "user", "content": [{"text": initial_content}]}
    ]
    conversation_log: list[dict] = [
        {"role": "user", "content": initial_content, "iteration": 0}
    ]
    final_text = ""

    for iteration in range(1, MAX_ITERATIONS + 1):
        if verbose:
            print(f"[iter {iteration:02d}] Calling model...", end=" ", flush=True)

        # Rolling window: keep first user message + last N messages
        if len(messages) > _CONTEXT_WINDOW + 1:
            windowed = messages[:1] + messages[-_CONTEXT_WINDOW:]
        else:
            windowed = messages

        response = bedrock_client.converse(
            modelId=model_name,
            system=[{"text": SYSTEM_PROMPT}],
            messages=windowed,
            inferenceConfig={"maxTokens": 8192, "temperature": 1.0},
            toolConfig={"tools": bedrock_tools},
        )

        token_usage.add(response.get("usage"))

        stop_reason = response.get("stopReason", "")
        assistant_message = response["output"]["message"]  # {"role": "assistant", "content": [...]}
        messages.append(assistant_message)

        # Parse content blocks
        text_parts: list[str] = []
        tool_use_blocks: list[dict] = []
        for block in assistant_message.get("content", []):
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tool_use_blocks.append(block["toolUse"])

        text_content = "\n".join(text_parts)

        conversation_log.append({
            "role": "assistant",
            "iteration": iteration,
            "text": text_content[:500],
            "tool_calls": [
                {"id": t["toolUseId"], "name": t["name"], "args": t["input"]}
                for t in tool_use_blocks
            ],
            "stop_reason": stop_reason,
        })

        if "TESTING_COMPLETE" in text_content:
            if verbose:
                print("TESTING_COMPLETE signal received.")
            final_text = text_content
            break

        if stop_reason == "end_turn" and not tool_use_blocks:
            if verbose:
                print("end_turn with no tool calls. Loop ending.")
            final_text = text_content
            break

        if not tool_use_blocks:
            if verbose:
                print(f"No toolUse blocks (stopReason={stop_reason}). Loop ending.")
            final_text = text_content
            break

        # Execute tools and collect results
        if verbose:
            tool_summary = ", ".join(t["name"] for t in tool_use_blocks)
            print(f"tools=[{tool_summary}]", end=" ", flush=True)

        tool_result_blocks: list[dict] = []
        for tool_use in tool_use_blocks:
            result_text = await execute_tool_call(
                mcp_session, tool_use["name"], tool_use["input"]
            )

            if verbose:
                preview = result_text[:200].replace("\n", " ")
                print(
                    f"\n         {tool_use['name']}"
                    f"({json.dumps(tool_use['input'])[:50]}): {preview}",
                    end="",
                )

            conversation_log.append({
                "role": "tool",
                "iteration": iteration,
                "tool_use_id": tool_use["toolUseId"],
                "tool_name": tool_use["name"],
                "tool_args": tool_use["input"],
                "result_preview": result_text[:300],
            })

            tool_result_blocks.append({
                "toolResult": {
                    "toolUseId": tool_use["toolUseId"],
                    "content": [{"text": result_text}],
                }
            })

        # All tool results go back in one user turn
        messages.append({"role": "user", "content": tool_result_blocks})

        if verbose:
            print()

    # ------------------------------------------------------------------
    # Summarization call — produce structured JSON findings
    # ------------------------------------------------------------------
    if verbose:
        print(f"\nSummarising findings from {len(conversation_log)} log entries...")

    observations = _extract_observations(conversation_log)
    summary_prompt = build_summary_prompt(url, observations)

    summary_response = bedrock_client.converse(
        modelId=model_name,
        system=[{"text": SUMMARY_SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": summary_prompt}]}],
        inferenceConfig={"maxTokens": 4096, "temperature": 1.0},
    )
    token_usage.add(summary_response.get("usage"))

    summary_text = ""
    for block in summary_response["output"]["message"].get("content", []):
        if "text" in block:
            summary_text += block["text"]

    conversation_log.append({
        "role": "assistant",
        "iteration": MAX_ITERATIONS + 1,
        "text": summary_text[:500],
        "tool_calls": [],
        "note": "Summarization call",
    })

    return summary_text, conversation_log


def _extract_observations(conversation_log: list[dict]) -> str:
    """
    Build a compact human-readable digest of what happened during the session.

    Args:
        conversation_log: List of iteration dicts from ``run_qa_loop``.

    Returns:
        Multi-line string summarising observations (or a fallback message).
    """
    pages_visited: list[str] = []
    console_errors: list[str] = []
    findings_notes: list[str] = []

    for entry in conversation_log:
        if entry.get("role") != "tool":
            continue

        tool = entry.get("tool_name", "")
        args = entry.get("tool_args", {})
        result = entry.get("result_preview", "")

        if tool == "browser_navigate":
            page_url = args.get("url", "")
            if "404 Not Found" in result or "404" in result:
                findings_notes.append(f"404 page: {page_url}")
            elif page_url:
                title = ""
                if "Page Title:" in result:
                    title = result.split("Page Title:")[-1].split("\n")[0].strip()
                pages_visited.append(f"{page_url} — {title}" if title else page_url)

        elif tool == "browser_console_messages":
            if "[ERROR]" in result:
                for line in result.split("\n"):
                    if "[ERROR]" in line:
                        console_errors.append(line.strip()[:200])

        elif tool in ("browser_evaluate", "browser_run_code"):
            result_lower = result.lower()
            if "logout" in result_lower:
                findings_notes.append("Login succeeded with test credentials")
            if "invalid" in result_lower and "username" in str(args).lower():
                findings_notes.append("Invalid credentials: error message shown")

    lines: list[str] = []
    if pages_visited:
        lines.append("PAGES VISITED:")
        lines.extend(f"  - {p}" for p in pages_visited[:20])
    if console_errors:
        lines.append("\nCONSOLE ERRORS:")
        lines.extend(f"  - {e}" for e in list(dict.fromkeys(console_errors))[:10])
    if findings_notes:
        lines.append("\nKEY OBSERVATIONS:")
        lines.extend(f"  - {n}" for n in findings_notes)

    return "\n".join(lines) if lines else "No significant observations recorded."
