"""
MCP tool schema conversion and execution for the Bedrock Converse API.

Responsibilities:
  - Convert MCP tool schemas to Bedrock's ``toolSpec`` format
  - Strip JSON Schema meta-fields that Bedrock does not accept
  - Execute tool calls through an active MCP session and return text results
"""

from __future__ import annotations

MAX_TOOL_RESULT_LEN = 4000  # chars — truncate long MCP results to save tokens


def mcp_tools_to_bedrock(mcp_tools: list) -> list[dict]:
    """
    Convert MCP tool objects to Bedrock Converse tool definitions.

    Args:
        mcp_tools: Tool objects from ``mcp_session.list_tools().tools``.

    Returns:
        List of dicts in Bedrock toolSpec format.
    """
    tools = []
    for tool in mcp_tools:
        schema = tool.inputSchema if tool.inputSchema else {}
        if "type" not in schema:
            schema = {"type": "object", "properties": {}}
        tools.append({
            "toolSpec": {
                "name": tool.name,
                "description": tool.description or f"Playwright tool: {tool.name}",
                "inputSchema": {"json": _clean_schema(schema)},
            }
        })
    return tools


def _clean_schema(schema: dict) -> dict:
    """Recursively remove JSON Schema meta-fields not accepted by Claude."""
    STRIP_KEYS = {"$schema", "$id", "$comment"}
    if not isinstance(schema, dict):
        return schema
    cleaned = {}
    for k, v in schema.items():
        if k in STRIP_KEYS:
            continue
        if isinstance(v, dict):
            cleaned[k] = _clean_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [_clean_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            cleaned[k] = v
    return cleaned


async def execute_tool_call(
    mcp_session,
    tool_name: str,
    tool_args: dict,
) -> str:
    """
    Execute a single tool call through the MCP session.

    Args:
        mcp_session: Active MCP ``ClientSession``.
        tool_name:   Name of the tool to invoke.
        tool_args:   Arguments dict matching the tool's input schema.

    Returns:
        String result (truncated to ``MAX_TOOL_RESULT_LEN`` if necessary).
    """
    try:
        result = await mcp_session.call_tool(tool_name, tool_args)
        if result.content:
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
                elif hasattr(item, "data"):
                    parts.append(f"[binary data: {len(item.data)} bytes]")
                else:
                    parts.append(str(item))
            full_text = "\n".join(parts)
        else:
            full_text = "(empty result)"

        if len(full_text) > MAX_TOOL_RESULT_LEN:
            full_text = (
                full_text[:MAX_TOOL_RESULT_LEN]
                + f"\n... [truncated, {len(full_text)} total chars]"
            )
        return full_text

    except Exception as exc:
        return f"[TOOL ERROR] {tool_name} failed: {type(exc).__name__}: {exc}"
