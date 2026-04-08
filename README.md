# Autonomous QA

> AI-powered, multi-agent website QA testing system. Point it at a URL — it maps the site, generates and executes tests in a real browser, verifies results, and delivers an HTML report with a coherent summary.

```
qa-auto https://staging.myapp.com --prd ./requirements.md
```

**What it does:** Replaces 60–75% of manual QA effort. Handles regression, smoke, sanity, E2E, boundary, visual, and security surface testing — orchestrated by specialized AI agents talking to a real browser via Playwright MCP.

**What it doesn't do:** Usability testing, deep penetration testing, business logic validation, cognitive accessibility assessment. These stay human.

---

## Why this exists

Modern teams ship daily. QA cycles take days. The gap keeps growing.

A full manual QA cycle on a 30-page site takes ~30 hours: test plan creation (4h) + test case writing (8h) + execution (8h) + bug docs (2h) + regression retest (4h) + reporting (2h). This system does it in minutes.

**Competitors exist** (Bug0, QA.tech, mabl, Functionize) — but they all do browser-only testing. Nobody unifies functional testing + site mapping + intelligent test generation + verification + structured reporting into a single AI-orchestrated multi-agent system. That's the gap we fill.

---

## Architecture

### Design principles

1. **Compartmentalized agents** — Each agent has a single responsibility and runs in its own fresh context. No shared conversation state between agents. This prevents context rot on long sessions.
2. **Deterministic orchestration** — The orchestrator follows a fixed two-phase flow (discovery → test+report). No ambiguity about what runs when.
3. **Intelligence in the tool calls** — The orchestrator decides *what* to test and *how* to frame each mission brief. Sub-agents decide *how* to execute. The LLM's reasoning happens at every delegation, not just at the start.

### Two-phase flow

```
══════════════════════════════════════════
 PHASE 1: DISCOVERY
══════════════════════════════════════════

 Orchestrator
   └── invoke_agent("crawler", mission_brief)
         │
         Crawler ──► Playwright MCP ──► site_map.json
                     (navigates site,       pages, forms,
                      follows all links)    auth walls,
                                            tech stack,
                                            nav graph


══════════════════════════════════════════
 PHASE 2: TEST · VERIFY · REPORT
══════════════════════════════════════════

 Orchestrator (has full site_map)
   │
   ├── invoke_agent("test_generator", site_map + test strategy)
   │     │
   │     TestGen ──► Playwright MCP ──► findings.json
   │                 (generates AND        test results,
   │                  executes tests       evidence,
   │                  across whole site)   observations
   │
   ├── invoke_agent("verifier", findings)
   │     │
   │     Verifier ──► [no tools] ──► verdicts.json
   │                                  PASS / FAIL / FLAKY
   │                                  per finding + severity
   │
   └── invoke_agent("report_generator", verdicts + site_map)
         │
         ReportGen ──► [no tools] ──► report.html
                                       report.md
```

**Orchestrator total iterations: ~5–8 `invoke_agent` calls. It never touches Playwright.**

### How `invoke_agent` works

The orchestrator has one tool: `invoke_agent(agent_id, mission_brief)`. When it calls it:

1. Python loads `agents/{agent_id}/skills.md` as the sub-agent's system prompt
2. Python loads `agents/{agent_id}/manifest.json` to read `requires_tools`
3. Only the tools that agent needs are passed to Bedrock (Playwright tools for Crawler and TestGen; none for Verifier and ReportGen)
4. A fresh Bedrock Converse call is made — the sub-agent has zero memory of prior agents
5. The sub-agent runs its own tool loop (2–10 iterations)
6. The result is returned to the orchestrator as a `toolResult` and the orchestrator continues

This is what keeps context clean: Crawler doesn't know about TestGen's run. TestGen doesn't see the Crawler's raw conversation. Each agent gets exactly the information it needs in its mission brief — no more.

### Agents

| Agent | Tools | Input | Output |
|-------|-------|-------|--------|
| **Orchestrator** | `invoke_agent` only | URL + PRD | Delegates to all sub-agents |
| **Crawler** | Playwright MCP (all) | URL + crawl instructions | `site_map.json` |
| **TestGen** | Playwright MCP (all) | `site_map.json` + test strategy | `findings.json` |
| **Verifier** | None | `findings.json` | `verdicts.json` (PASS/FAIL/FLAKY) |
| **ReportGen** | None | `verdicts.json` + `site_map.json` | `report.html` + `report.md` |

---

## Project structure

```
autonomous-qa/
├── src/
│   ├── cli.py              # Entry point: qa-auto <url> [options]
│   ├── main.py             # Session orchestration, Bedrock + MCP init
│   ├── runner.py           # Orchestrator loop + invoke_agent handler
│   ├── prompts.py          # Orchestrator system prompt
│   ├── tools.py            # MCP → Bedrock schema conversion + execution
│   ├── report.py           # Output file writing
│   └── token_usage.py      # Token tracking with Bedrock pricing
├── agents/
│   ├── orchestrator/
│   │   ├── manifest.json
│   │   └── skills.md       # Two-phase flow instructions, mission brief templates
│   ├── crawler/
│   │   ├── manifest.json
│   │   └── skills.md       # Site mapping heuristics, what to extract
│   ├── test_generator/
│   │   ├── manifest.json
│   │   └── skills.md       # Test patterns, execution instructions, findings format
│   ├── verifier/
│   │   ├── manifest.json
│   │   └── skills.md       # PASS/FAIL/FLAKY rules, severity classification
│   └── report_generator/
│       ├── manifest.json
│       └── skills.md       # HTML report template, chart generation, summary writing
├── sessions/               # Runtime output (gitignored)
│   └── {session-id}/
│       ├── site_map.json
│       ├── findings.json
│       ├── verdicts.json
│       ├── report.html
│       ├── report.md
│       └── raw_conversation.json
├── pyproject.toml
├── qa-auto.example.yaml
└── .gitignore
```

---

## Tech stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Dev velocity. MCP is JSON-RPC (language-agnostic) |
| LLM API | AWS Bedrock Converse API (boto3) | Claude family, no proxy, production-ready |
| Browser | Playwright MCP (`@playwright/mcp`) | 70+ tools, accessibility tree, cross-browser |
| MCP client | `mcp` Python SDK | stdio connection to Playwright MCP subprocess |
| Config | PyYAML | `qa-auto.yaml` with env var substitution |
| Validation | Pydantic v2 | Manifest schema validation |
| CLI | argparse (stdlib) | No extra dependencies |

**AWS credentials** are resolved by boto3 in the standard order: environment variables → `~/.aws/credentials` → IAM role.

---

## Configuration

```yaml
# qa-auto.yaml
target:
  url: "https://staging.myapp.com"
  prd: "./requirements.md"           # optional — shapes test strategy
  auth_cookie: ${AUTH_COOKIE}         # optional
  exclude_paths: ["/admin", "/internal"]

browser:
  engine: chromium                   # chromium | firefox | webkit
  headless: true

models:
  primary: "anthropic.claude-3-5-sonnet-20241022-v2:0"   # orchestrator
  sub: "anthropic.claude-3-5-haiku-20241022-v1:0"        # sub-agents (cheaper)

budget:
  max_per_session: 10.00             # USD, abort gracefully at limit

reporting:
  formats: [html, markdown]
```

---

## Getting started

### Prerequisites

```bash
python --version    # 3.11+
node --version      # for Playwright MCP via npx

# AWS credentials (one of):
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="us-east-1"
# or configure ~/.aws/credentials
```

### Install and run

```bash
git clone <repo-url> && cd autonomous-qa
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Verify Playwright MCP works
npx @playwright/mcp@latest --headless
# Should print available tools, then Ctrl+C

# Copy and edit config
cp qa-auto.example.yaml qa-auto.yaml

# Run
qa-auto https://toscrape.com
qa-auto https://staging.myapp.com --prd ./requirements.md --headless false
```

### Output

Each session writes to `sessions/{domain}_{timestamp}/`:

| File | Description |
|------|-------------|
| `report.html` | Full HTML report with charts, severity breakdown, per-finding details |
| `report.md` | Markdown summary — shareable in PRs, Slack, Jira |
| `site_map.json` | Discovered pages, forms, auth walls, tech stack |
| `findings.json` | Raw test results from TestGen |
| `verdicts.json` | Classified results from Verifier |
| `raw_conversation.json` | Full agent conversation log for debugging |
| `cost.json` | Token usage and estimated USD cost |

---

## Testing coverage (this PoC)

| Testing type | AI coverage | Notes |
|-------------|------------|-------|
| Smoke testing | 95% | |
| Sanity testing | 95% | |
| Regression testing | 90% | |
| End-to-end testing | 90% | |
| Boundary / edge case | 80% | |
| Visual regression | 80% | Screenshot comparison |
| Security surface | 50% | XSS, auth bypass, open redirects — not deep pentest |
| Accessibility | 45% | Basic checks only |
| Usability | 0% | Human-only, always |

**Overall: ~60–65% of manual QA effort covered in this PoC.**

---

## What's next (post-PoC)

The PoC proves the multi-agent architecture works end-to-end on real sites. The next phase adds:

- **Cross-browser + responsive** — run TestGen on Firefox, WebKit, mobile viewports
- **Load testing** — JMeter MCP integration for API endpoint stress testing
- **API testing** — Postman MCP for REST endpoint validation
- **Observability correlation** — Grafana + Sentry MCP to correlate test failures with infra metrics and application errors
- **CI/CD integration** — GitHub Action, webhook mode, auto-create Jira tickets on FAIL
- **Incremental testing** — diff site graph vs previous run, test only changed pages (50–70% cost reduction)

---

## Manifest schema

```json
{
  "id": "crawler",
  "name": "Site Crawler",
  "version": "1.0.0",
  "type": "sub-agent",
  "requires_tools": ["browser_navigate", "browser_snapshot", "browser_click",
                     "browser_console_messages", "browser_network_requests"],
  "model_tier": "sub",
  "input_format": "mission_brief_markdown",
  "output_format": "site_map_json",
  "description": "Systematically maps a website: all pages, forms, auth walls, tech stack"
}
```

---

## Competitive landscape

| Competitor | What they do | What we do differently |
|-----------|-------------|----------------------|
| **Bug0** ($250–2500/mo) | AI agents + browser E2E. Playwright-based. | Multi-agent architecture with compartmentalized context. Self-hosted. Open. |
| **QA.tech** | AI learns site, autonomous regression. SaaS. | Two-phase discovery → test. PRD-driven test strategy. |
| **mabl** | AI-enhanced test automation. Enterprise. | mabl requires defining flows. We discover autonomously. |
| **Functionize** | Enterprise AI test automation. Self-healing. | SaaS, expensive. We're open, self-hosted, extensible. |

**Our actual moat:** A multi-agent system where each agent has a single job, fresh context, and domain-specific skills. The orchestrator is a pure coordinator. The result is a system that scales in depth (better skills.md = better tests) without growing in complexity.

---

*Built by Amitabh · April 2026*
