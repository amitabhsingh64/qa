# Dev Session 2 — Summary
**Date:** 2026-04-09
**Presentation deadline:** Tuesday 2026-04-15

---

## What we built today

This session focused entirely on the **observability, reliability, and reporting layers** of the PoC. The core agentic pipeline (orchestrator → crawler → test_generator → verifier → report_generator) was already wired; today we hardened everything around it.

### 1. Sub-agent output status contracts

Every sub-agent now signals whether it finished. Each `skills.md` was updated:

| Agent | Success signal | Cap signal |
|---|---|---|
| Crawler | `"status": "complete"` as first JSON key | `"status": "capped"` JSON with `completed / skipped / in_progress / narrative` |
| TestGen | same | same, `completed.findings` holds partial results |
| Verifier | same | same, `completed.verdicts` holds partial results + counts |
| ReportGen | `<body data-status="complete">` | `"status": "capped"` JSON with `completed.partial_html` |

All four agents also received a `## When you reach your iteration limit` section with exact JSON format to produce when capped.

### 2. Retry budget config + enforcement (`src/config.py`, `src/runner.py`)

Added `RetryConfig` to the config model:

```yaml
retry:
  max_attempts_per_agent: 3
  max_total_retries_per_session: 5
```

Runner enforces before every `invoke_agent` dispatch:
- If `attempt > max_attempts_per_agent` → returns structured `{"status": "error", "error": "retry_budget_exceeded", ...}` to orchestrator, no sub-agent call made
- If `attempt > 1` and `total_retries >= max_total_retries_per_session` → returns `{"status": "error", "error": "session_retry_budget_exceeded", ...}`
- Config loaded in `main.py` via `Config.load()`, passed as `retry_config` to `run_qa_loop`

### 3. Invocation telemetry (`src/token_usage.py`)

Replaced `record_invocation()` with a two-step API:

- **`begin_invocation(agent_id, attempt, previous_invocation_id, started_at) → inv_id`** — writes a `"running"` record immediately, before the first LLM call. Ensures the invocation is tracked even if the call raises.
- **`close_invocation(inv_id, status, iterations_used, iterations_limit, started_at, tokens_before, capped_summary=None, retry_scope=None)`** — fills in final status, duration, token delta, and optional metadata.

`run_sub_agent` wraps the entire loop in `try/except/else/finally`:
- `finally` always calls `close_invocation` (even on crash)
- `else` (no exception path) computes retry counts before closing

Each invocation record in `agent_invocations`:

```json
{
  "invocation_id": "inv_002",
  "agent_id": "test_generator",
  "attempt": 2,
  "previous_invocation_id": "inv_001",
  "status": "complete",
  "iterations_used": 87,
  "iterations_limit": 150,
  "started_at": "...",
  "duration_seconds": 312.4,
  "tokens": { "input": 42000, "output": 18000 },
  "capped_summary": null,
  "retry_scope": {
    "reason": "previous_attempt_capped",
    "items_targeted": ["search form XSS probe", "navigation 404 checks"],
    "items_completed": 2,
    "items_still_missing": 0
  }
}
```

### 4. Retry scope tracking (`src/runner.py`)

When `attempt > 1`, the dispatch block:
1. Parses the orchestrator's mission brief for a `## Retry context` section (regex-extracted bullet list → `items_targeted`)
2. Looks up previous invocation status → maps to `reason` (`previous_attempt_capped | previous_attempt_errored | explicit_orchestrator_decision`)
3. Builds partial `retry_scope`, passes to `run_sub_agent`
4. After run completes (`else` branch), calls `_compute_retry_counts`:
   - **Verifier**: matches `items_targeted` against `finding_id` in the verdicts array
   - **Crawler**: matches `items_targeted` against `pages[].url`
   - **TestGen / ReportGen**: returns `(None, None)` — free-text targets not matchable

### 5. Session-level retry_summary rollup (`src/token_usage.py`)

New method `compute_retry_summary()` — pure derivation from `_invocations`, no new state:

```json
{
  "total_invocations": 5,
  "total_unique_agents": 4,
  "total_retries": 1,
  "agents_with_retries": ["test_generator"],
  "max_attempts_for_any_agent": 2,
  "capped_count": 1,
  "errored_count": 0,
  "completed_count": 4
}
```

Included in `to_dict()` → surfaces in `cost.json` between `breakdown_by_agent` and `agent_invocations`.

### 6. Orchestrator retry decision logic (`agents/orchestrator/skills.md`)

Added **"Handling capped and incomplete sub-agent results"** — a five-step decision procedure:

1. Read capped summary (`completed`, `skipped`, `in_progress`, `narrative`)
2. Check budget (3 per agent / 5 session total)
3. Go/no-go criteria with explicit lists for both paths
4. If retrying: write a narrower `## Retry context` brief (specific items only, previous `narrative` as background)
5. If not retrying: write a `## Coverage gaps` section for the report generator

Also added:
- **"Retrying a Sub-Agent"** section with exact `## Retry context` format (previous invocation ID + specific bullet items — no prose, no "Note:" lines, no "Previous invocation" bullet)
- **"Sub-Agent Result Status"** reference section (complete / capped / error)
- Rule 2 updated: check session state before invoking — don't re-invoke agents that already returned `complete`

### 7. Run health in the HTML report (`agents/report_generator/skills.md`)

ReportGen now receives `agent_invocations` and `retry_summary`. Report structure updated to add two new sections:

**Section 3 — Run Health** (after summary cards, before severity chart):
- Case A — clean: green banner, "All sub-agents completed on first attempt"
- Case B — recovered: amber banner, "N retries required, missing items recovered"
- Case C — incomplete: red banner + bullet list of unaddressed skipped items + "Consider running a focused session"

Inline CSS with `run-health--complete / --recovered / --incomplete` classes, colour-coded border-left.

**Section 4 — Invocation timeline** (collapsible `<details>`):
- Table: inv_id | agent | attempt | status (badge) | duration | tokens in/out | notes
- Green badge for complete, yellow for capped, red for error
- Row background tinting: capped rows `#fffbeb`, error rows `#fef2f2`
- Notes column: shows `capped_summary.narrative` or `retry_scope.reason + counts`

Telemetry is injected into the orchestrator's context by appending a `## Session telemetry` block to the verifier's tool result (runner.py), so the orchestrator has it available when composing the ReportGen mission brief.

### 8. Infrastructure fixes

- **boto3 `read_timeout` 60s → 300s** — ayushman hit a `ReadTimeoutError` at test_generator iteration 114; root cause was the default boto3 timeout being too short for long Sonnet responses. Fixed in `main.py`.
- **`retries mode: "standard"` → `"adaptive"`, `max_attempts: 2` → `8`** — handles `ServiceUnavailableException: Too many connections` from Bedrock by using adaptive rate control with more retry headroom.
- **`ReadTimeoutError` caught in `run_sub_agent`** — converts to a structured `{"status": "error", "error": "bedrock_read_timeout", ...}` returned to orchestrator instead of crashing the MCP session.

---

## Current codebase state

```
qa/
├── src/
│   ├── main.py          — session entry point; loads Config, builds boto3 client
│   │                      (read_timeout=300, adaptive retries), passes retry_config
│   ├── runner.py        — orchestrator loop + sub-agent dispatch
│   │                      retry budget enforcement, retry_scope building,
│   │                      verifier telemetry injection, ReadTimeoutError handling
│   ├── token_usage.py   — two-step invocation API (begin/close),
│   │                      compute_retry_summary(), to_dict() includes retry_summary
│   ├── config.py        — RetryConfig(max_attempts_per_agent=3,
│   │                      max_total_retries_per_session=5), wired into Config
│   ├── prompts.py       — build_orchestrator_prompt(url, prd_content)
│   ├── tools.py         — MCP tool conversion + execute_tool_call
│   └── cli.py           — CLI entry point
│
├── agents/
│   ├── orchestrator/    — skills.md: two-phase flow, retry decision logic,
│   │                      ## Retry context format, sub-agent status reference
│   ├── crawler/         — skills.md: status:"complete" output,
│   │                      ## When you reach your iteration limit (capped JSON)
│   │                      manifest.json: max_iterations=50, 6 Playwright tools
│   ├── test_generator/  — skills.md: status:"complete" output,
│   │                      ## When you reach your iteration limit
│   │                      manifest.json: max_iterations=150, 9 Playwright tools
│   ├── verifier/        — skills.md: status:"complete" output,
│   │                      ## When you reach your iteration limit
│   │                      manifest.json: max_iterations=5, no tools (model_tier=sub)
│   └── report_generator/ — skills.md: consumes agent_invocations + retry_summary,
│                           Run Health section (3 cases), Invocation timeline section
│                           manifest.json: max_iterations=5, no tools
│
├── qa-auto.example.yaml — retry: block added
└── dev_session/
    ├── session_1/       — prior session notes
    └── session_2/       — this file
```

### Key data flows

```
run_qa_loop
  ├── dispatch: check budget (prior_invocations count vs retry_config)
  ├── dispatch: build retry_scope from ## Retry context in mission_brief
  │
  └── run_sub_agent
        ├── begin_invocation()   ← writes "running" record BEFORE first LLM call
        ├── [LLM loop]
        │     ├── on cap: _request_cap_summary() → capped_summary
        │     └── on ReadTimeoutError: return structured error JSON (no crash)
        ├── [else clause]: _compute_retry_counts() → fills retry_scope counts
        └── close_invocation()   ← always runs (finally), fills final record
  │
  ├── after verifier: append telemetry snapshot to tool_result
  │     (agent_invocations + retry_summary → orchestrator sees it for ReportGen brief)
  │
  └── token_usage.to_dict()
        ├── breakdown_by_agent
        ├── retry_summary          ← compute_retry_summary() called at serialisation
        └── agent_invocations      ← full invocation chain
```

---

## What is NOT done yet

- End-to-end run with retries to verify `retry_scope.items_completed` computation works correctly for Verifier
- ReportGen HTML output has not been verified in a browser — the Run Health and Invocation timeline sections are new and untested
- The `## Coverage gaps` section (produced by orchestrator before calling ReportGen when there are unrecovered gaps) has not been observed in a real session yet
- `agents/orchestrator/manifest.json` currently exists but content not confirmed — need to verify `max_iterations` is set to something appropriate (currently 50)
- No automated tests exist for any of the new code paths (retry budget enforcement, `begin/close_invocation`, `compute_retry_summary`, `_compute_retry_counts`, `_parse_retry_context`)

---

## Next likely tasks

1. Run end-to-end on a real site and observe whether ReportGen produces correct Run Health HTML
2. Verify `cost.json` structure includes `retry_summary` and `agent_invocations` correctly
3. README update to reflect the new reliability and observability features
4. Consider adding a dry-run mode that prints the orchestrator's planned mission briefs without executing them
