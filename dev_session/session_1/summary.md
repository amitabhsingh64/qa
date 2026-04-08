# Dev Session 1 — April 6, 2026

## Goal
Scaffold the autonomous-qa project and get Phase 0 (proof of concept) running end-to-end.

---

## What We Built

### Project Scaffold
Created the full directory structure from scratch:
- `src/phase0.py` — fully implemented Phase 0 agentic QA script
- `src/core/` — 7 stub modules with typed signatures ready for Phase 1
- `agents/` — 8 agent folders (orchestrator, test_generator, verifier, load_tester, api_tester, security_tester, infra_observer, error_observer), each with `manifest.json` + `skills.md`
- `pyproject.toml`, `.gitignore`, `qa-auto.example.yaml`

### Phase 0 — `src/phase0.py`
A single-script autonomous QA agent that:
1. Accepts a URL + optional PRD file as CLI args
2. Launches Playwright MCP via `npx @playwright/mcp@latest --headless`
3. Connects via MCP stdio protocol
4. Runs an agentic loop (up to 50 iterations): LLM → tool calls → MCP execution → feed results back
5. After the loop, extracts observations from the conversation log and runs a separate summarization call
6. Writes `report.md`, `raw_conversation.json`, `cost.json` to `sessions/phase0/`

---

## API / Model Journey

We went through several providers before finding a working setup:

| Attempt | Provider | Model | Outcome |
|---------|----------|-------|---------|
| 1 | Gemini (direct) | gemini-2.5-pro | ❌ Free tier quota = 0, billing required |
| 2 | Gemini (direct) | gemini-2.0-flash | ❌ Same issue, limit: 0 |
| 3 | OpenRouter | google/gemini-2.0-flash-exp:free | ❌ Model not found (removed) |
| 4 | OpenRouter | google/gemini-2.5-pro-exp-03-25:free | ❌ Model not found |
| 5 | OpenRouter | meta-llama/llama-3.3-70b-instruct:free | ❌ Rate limited (Venice upstream) |
| 6 | xAI | grok-3-mini | ❌ No credits on new account |
| 7 | Ollama (local) | gpt-oss:20b | ⚠️ Too small — hallucinated tool names, went in circles |
| 8 | Ollama (local) | gpt-oss:120b-cloud | ⚠️ Works but never wrote final JSON report |
| 9 | Ollama (local) | deepseek-v3.2:cloud | ✅ Working — used XML-style tool calls |

**Current setup:** Ollama local → `deepseek-v3.2:cloud`

---

## Bugs Fixed During Session

### 1. `$schema` field in Gemini tool declarations
**Error:** `Extra inputs are not permitted` for `$schema` field
**Fix:** Added `clean_schema_for_gemini()` (later `_clean_schema()`) to strip JSON Schema meta-fields before passing to LLM APIs.

### 2. Playwright chrome binary not installed
**Error:** `Chromium distribution 'chrome' is not found`
**Fix:** `npx playwright install chrome` (not just `chromium`)

### 3. Free tier quota = 0
**Error:** `429 RESOURCE_EXHAUSTED, limit: 0`
**Cause:** Gemini API key project had no billing enabled — free tier quota was literally zero
**Fix:** Switched to OpenAI-compatible interface, eventually to Ollama local

### 4. Context window explosion
**Symptom:** 390K input tokens after 50 iterations (13 min runtime)
**Cause:** Full conversation history + large tool results (page snapshots, HTML) sent every iteration
**Fix:**
- Reduced tool result truncation: 8000 → 1000 chars
- Added rolling context window: keep system + first user + last 20 messages only

### 5. Model never writes final JSON report
**Symptom:** Agent explored well but hit 50 iterations without producing structured output
**Fix:** After the exploration loop, extract a compact observations digest from the conversation log, then make a separate focused summarization call with just that digest.

### 6. DeepSeek XML-style tool calls
**Symptom:** `[iter 01] No tool calls (finish_reason=stop)` — loop ended immediately
**Cause:** DeepSeek V3 via Ollama emits tool calls as XML in text content (`<function_calls><invoke>...`) instead of OpenAI's `tool_calls` field
**Fix:** Added `_parse_xml_tool_calls()` to detect and parse XML tool calls from text. Results fed back as `role: user` messages (not `role: tool`) since tool_call_id is fake.

### 7. `dict.fromkeys()[:10]` KeyError
**Error:** `KeyError: slice(None, 10, None)` in `_extract_observations()`
**Cause:** `dict.fromkeys()` returns a dict, not a list — dicts don't support slice indexing
**Fix:** `list(dict.fromkeys(console_errors))[:10]`

---

## Current State (End of Session)

- ✅ Project fully scaffolded
- ✅ Phase 0 script runs end-to-end with DeepSeek V3.2 via Ollama
- ✅ Agent navigates sites, tests flows, finds real bugs (favicon 404, auth bypass testing, login flow)
- ✅ Rolling context window keeps tokens manageable (~334K for 50 iterations)
- ✅ Observation extraction + summarization call architecture in place
- ✅ Final report confirmed producing real findings — dict bug fix verified (see below)
- ⚠️ `browser_click` and `browser_type` tools frequently fail with "Ref not found" — model works around with `browser_run_code` instead

---

### 8. `dict.fromkeys()[:10]` slice — verified fix + successful run

**Verification run:** `python src/phase0.py https://toscrape.com` (2026-04-06 10:26 UTC)

**Result:** 2 issues found, 7 pages visited, 23m 0s, 334K input tokens.

| ID | Severity | Finding |
|----|----------|---------|
| F001 | HIGH | Basket page `/basket/` returns 404 — broken e-commerce flow |
| F002 | LOW | Missing `favicon.ico` — console 404 error on main page |

**Pages tested:**

| URL | Status |
|-----|--------|
| https://toscrape.com | 200 |
| http://books.toscrape.com | 200 |
| http://books.toscrape.com/catalogue/category/books_1/index.html | 200 |
| http://books.toscrape.com/catalogue/category/books/travel_2/index.html | 200 |
| http://books.toscrape.com/index.html | 200 |
| http://books.toscrape.com/catalogue/category/books/mystery_3/index.html | 200 |
| http://books.toscrape.com/basket/ | **404** |

Phase 0 is end-to-end complete. ✅

---

## Next Session — Phase 1 Tasks

Per the README roadmap:
- `1.1` Build `agent_runner.py` — generic agent execution loop
- `1.2` Model routing from manifest `model_tier`
- `1.3` Tool filtering from manifest `requires_tools`
- `1.4` Build `registry.py` — scan `/agents/*/manifest.json`
- `1.7` Build `session.py` — session directory + state.json
- `1.8` Build `blackboard.py` — append-only conversation log
- `1.9` Build `mcp_client.py` — multi-MCP connection manager
- `1.11` Build `cli.py` — `qa-auto <url>` entry point

**Gate 1 test:** Create a dummy `/agents/echo/` agent. Does the registry discover it? Does `run_agent()` execute it?
