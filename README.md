# Autonomous QA

> AI-powered, multi-agent website QA testing system. Point it at a URL — it explores the site, generates tests, executes them in a real browser, correlates with infrastructure data, and delivers an actionable QA report.

```
qa-auto https://staging.myapp.com --prd ./requirements.md
```

**What it does:** Replaces 60–75% of manual QA effort. Handles regression, smoke, sanity, E2E, cross-browser, responsive, visual, boundary, load, API, and security surface testing — orchestrated by specialized AI agents talking to real tools via MCP.

**What it doesn't do:** Usability testing, deep penetration testing, business logic validation, cognitive accessibility assessment. These stay human.

---

## Why this exists

Modern teams ship daily. QA cycles take days. The gap keeps growing.

A full manual QA cycle on a 30-page site takes ~30 hours: test plan creation (4h) + test case writing (8h) + execution (8h) + bug docs (2h) + regression retest (4h) + reporting (2h). Our system does it in ~5 minutes. API costs depend on provider — $0 on Gemini free tier (prototyping), ~$3.80 on Claude (production).

**Competitors exist** (Bug0, QA.tech, mabl, Functionize) — but they all do browser-only testing. Nobody unifies functional testing + load testing + API testing + infrastructure observability + application error correlation into a single AI-orchestrated system. That's the gap we fill.

---

## Architecture

### Three design principles

1. **Modularity over monoliths** — Every agent is a self-contained plugin. New testing capabilities = new folder. No orchestrator code changes.
2. **Deterministic first, LLM second** — Use fast rule-based logic (keyword matching, pattern detection) where possible. Invoke LLMs only for genuinely ambiguous or creative tasks.
3. **Observable by default** — Every action, decision, and finding logged to a shared blackboard. Nothing happens in the dark.

### Three layers

```
┌─────────────────────────────────────────────────────────────────┐
│  COMMUNICATION LAYER                                            │
│  conversations.md (blackboard) | site_model.json | session state│
├─────────────────────────────────────────────────────────────────┤
│  AGENT LAYER                                                    │
│                                                                 │
│  ┌─────────────────────────────────────┐                       │
│  │         ORCHESTRATOR (primary)       │                       │
│  │  Plans, delegates, coordinates all   │                       │
│  └──┬───┬───┬───┬───┬───┬───┬──────────┘                       │
│     │   │   │   │   │   │   │                                  │
│     ▼   ▼   ▼   ▼   ▼   ▼   ▼                                  │
│  TestGen Verifier Security LoadTest APITest InfraObs ErrorObs  │
│  (sub)   (sub)    (sub)    (sub)    (sub)   (sub)    (sub)     │
│                                                                 │
│  tier1_locator.py — deterministic element finder (in core/)     │
├─────────────────────────────────────────────────────────────────┤
│  TOOL LAYER — MCP servers                                       │
│                                                                 │
│  Playwright MCP     JMeter MCP      Postman MCP                 │
│  (browser)          (load testing)  (API testing)               │
│                                                                 │
│  Grafana MCP        Sentry MCP                                  │
│  (infra metrics)    (app errors)     ← both optional            │
└─────────────────────────────────────────────────────────────────┘
```

### How agents call agents

The LLM is a brain in a jar. It decides what to do. Our code is the hands that execute.

```
1. Our code sends prompt + tools to the primary model (orchestrator)
2. Model responds with tool_use JSON: {"tool": "invoke_agent", "input": {...}}
3. Our code catches it → loads target agent's skills.md → makes SEPARATE LLM call
4. Sub-agent runs its OWN tool loop (2-4 iterations)
5. Sub-agent result returns to orchestrator as tool_result
6. Orchestrator continues — may invoke another agent or act directly
```

Two nested loops: outer (orchestrator, 50–100 iterations per session) and inner (sub-agent, 2–4 iterations per invocation). Hub-and-spoke topology — sub-agents never talk to each other.

### Four key files

| File | Purpose | Who writes it | Lifespan |
|------|---------|---------------|----------|
| `manifest.json` | Machine-readable agent contract (id, trigger, required tools, model tier) | Developer | Permanent |
| `skills.md` | Domain knowledge loaded as LLM system prompt. Testing heuristics, patterns. **The competitive moat.** | Developer | Permanent, evolving |
| `mission_brief.md` | Rich context per sub-agent invocation: PRD excerpt + page refs + blackboard observations + run history + edge cases | Orchestrator (at runtime) | Ephemeral (per invocation) |
| `conversations.md` | Append-only timestamped blackboard. Agents write observations, orchestrator curates excerpts. Full audit trail. | All agents (at runtime) | Per session |

### MCP server connections

| MCP Server | What it provides | Required? | Phase |
|------------|-----------------|-----------|-------|
| **Playwright MCP** | Browser automation: navigate, click, type, snapshot, screenshot, console, network | **Yes** | 0 |
| **JMeter MCP** | Load testing: create plan, run scenarios, response times, error rates | No | 5 |
| **Postman MCP** | API testing: run collections, validate schemas, test auth | No | 5 |
| **Grafana MCP** | Infrastructure correlation: PromQL metrics, LogQL logs, TraceQL traces | No (requires target to have Grafana) | 5 |
| **Sentry MCP** | Application error correlation: issues, stack traces, session replays, Seer analysis | No (requires target to have Sentry) | 5 |

Grafana and Sentry are query interfaces — they read from existing observability infrastructure the target company already has. If the target has no Grafana/Sentry, those agents simply don't activate.

---

## Project structure

```
autonomous-qa/
├── src/
│   ├── core/
│   │   ├── agent_runner.py      # Generic agent execution loop (~400 lines)
│   │   ├── mcp_client.py        # Multi-MCP server connection manager
│   │   ├── blackboard.py        # Append-only shared conversation log
│   │   ├── registry.py          # Scan /agents/, load manifests, validate tools
│   │   ├── session.py           # Session state, evidence directory
│   │   ├── site_model.py        # Site graph data structure
│   │   └── tier1_locator.py     # Deterministic keyword→ref matching
│   ├── cli.py                   # Entry point: qa-auto <url> [options]
│   └── config.py                # qa-auto.yaml loader
├── agents/
│   ├── orchestrator/
│   │   ├── manifest.json
│   │   └── skills.md            # 50+ testing heuristic patterns
│   ├── test_generator/
│   │   ├── manifest.json
│   │   └── skills.md
│   ├── verifier/
│   │   ├── manifest.json
│   │   └── skills.md
│   ├── load_tester/             # Phase 5
│   │   ├── manifest.json
│   │   └── skills.md
│   ├── api_tester/              # Phase 5
│   │   ├── manifest.json
│   │   └── skills.md
│   ├── security_tester/         # Phase 5
│   │   ├── manifest.json
│   │   └── skills.md
│   ├── infra_observer/          # Phase 5 (Grafana MCP)
│   │   ├── manifest.json
│   │   └── skills.md
│   └── error_observer/          # Phase 5 (Sentry MCP)
│       ├── manifest.json
│       └── skills.md
├── sessions/                    # Created at runtime
│   └── {session-id}/
│       ├── state.json
│       ├── conversations.md
│       ├── site_model.json
│       ├── report.json
│       ├── report.md
│       └── evidence/
├── site-models/                 # Persistent per-domain knowledge (schema-versioned)
│   └── {domain}.json            # Includes "schema_version" field for migration
├── tests/
├── pyproject.toml
├── qa-auto.yaml                 # Default config (gitignored — contains credentials)
├── qa-auto.example.yaml         # Checked-in template with placeholder values
├── .gitignore
└── README.md                    # This file
```

---

## .gitignore

```
sessions/               # Runtime artifacts, screenshots, state
qa-auto.yaml            # Contains credentials — use qa-auto.example.yaml as template
site-models/            # Per-domain learned data
.venv/
__pycache__/
*.pyc
```

---

## Tech stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Dev velocity. MCP is JSON-RPC (language-agnostic) |
| LLM API | Model-agnostic (OpenAI-compatible interface) | Gemini 2.5 Pro for prototyping; Claude family for later phases. Swap via config |
| MCP client | `mcp` Python SDK | Connect to all MCP servers via stdio/HTTP |
| Browser | Playwright MCP (`@playwright/mcp`) | 70+ tools, accessibility tree, cross-browser |
| Load testing | JMeter MCP (`jmeter-mcp-server`) | Community, Python package by QAInsights |
| API testing | Postman MCP (official) | Direct API endpoint testing |
| Observability | Grafana MCP (`mcp-grafana`) | Official, PromQL/LogQL/TraceQL queries |
| Error tracking | Sentry MCP (`mcp.sentry.dev`) | Official, hosted, OAuth |
| CLI | argparse (stdlib) | No dependencies |
| Config | PyYAML | qa-auto.yaml |
| Validation | Pydantic v2 | Manifest schema validation |

**Framework decision:** No framework. The most successful agent implementations use simple composable patterns. LangGraph (rigid state schema), CrewAI (poor logging), AutoGen (conversation metaphor mismatch) were all evaluated and rejected. Our core is ~400 lines of Python.

**Model-agnostic design:** The LLM interface is abstracted behind an OpenAI-compatible client. Swapping providers (Gemini → Claude → others) is a config change, not a code change. Prototyping uses Gemini 2.5 Pro (free tier); later phases will adopt Claude family models.

---

## Configuration

```yaml
# qa-auto.yaml
target:
  url: "https://staging.myapp.com"
  prd: "./requirements.md"           # optional
  auth_cookie: ${AUTH_COOKIE}         # optional; supports env var substitution
  exclude_paths: ["/admin", "/internal"]

browser:
  engine: chromium                   # chromium | firefox | webkit
  headless: true
  viewports: [1920x1080]            # add 768x1024, 375x812 for responsive

models:
  primary: gemini-2.5-pro            # orchestrator + all agents (prototyping)
  # primary: claude-opus-4-6         # orchestrator (later phases)
  # sub: claude-sonnet-4-6           # sub-agents (later phases)

budget:
  max_per_session: 10.00             # USD, abort gracefully at limit

# Optional MCP integrations (connect if target uses these)
grafana:
  enabled: false
  url: "https://myinstance.grafana.net"
  token: ${GRAFANA_TOKEN}
  read_only: true

sentry:
  enabled: false
  # Uses OAuth via mcp.sentry.dev — no token needed for cloud
  org: "my-org"
  project: "my-project"

reporting:
  formats: [json, markdown]          # add "html" in Phase 6
  jira:
    enabled: false
    url: "https://myorg.atlassian.net"
    project_key: "QA"
```

---

## Development phases

### Overview

| Phase | Name | Timeline | Effort | Deliverable | Gate |
|-------|------|----------|--------|-------------|------|
| **0** | Proof of concept | 3 days | 8h | Single script → raw QA report | Is output useful? |
| **1** | Foundation | Weeks 1–2 | 24h | Agent runner + registry + MCP client + CLI | Can you add agents by folder? |
| **2** | Discovery & planning | Weeks 3–4 | 20h | Site crawl + heuristic test plans + PRD | Are plans non-trivial? |
| **3** | Execution & verification | Weeks 5–7 | 32h | Full loop: URL → report (**MVP**) | Catches real bugs? |
| **4** | Quality & resilience | Weeks 8–9 | 24h | Flakiness, caching, cross-browser | — |
| **5** | MCP expansion | Weeks 10–12 | 32h | JMeter + Postman + Grafana + Sentry + security | QA engineer trusts it? |
| **6** | Integration | Weeks 13–15 | 24h | CI/CD, HTML reports, Jira, watch mode | — |

**Total: ~164 hours across 15 weeks**

---

### Phase 0 — Proof of concept

> **Goal:** Validate that LLM + Playwright MCP can produce useful QA output before investing in infrastructure.
> **Time:** 3 days | **Effort:** 8 hours

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 0.1 | Set up Python project: pyproject.toml, `google-genai` SDK, `mcp` client | 1h | — |
| 0.2 | Launch Playwright MCP as subprocess (`npx @playwright/mcp@latest --headless`), verify connection | 1h | 0.1 |
| 0.3 | Write minimal script: hardcoded system prompt + Gemini 2.5 Pro + Playwright tools attached | 1h | 0.2 |
| 0.4 | Implement basic tool-calling loop: send → catch tool_use → execute via MCP → feed result → repeat until end_turn | 2h | 0.3 |
| 0.5 | Test on 3 sites: static site, login form, React SPA. Record behavior, findings, token usage | 2h | 0.4 |
| 0.6 | Write findings to markdown report. Print cost breakdown to console | 1h | 0.5 |

**Output:** ~100-line Python script. Takes a URL, produces a rough markdown report.

#### 🚦 Gate 0

Show the raw report to 2–3 people. Ask: "Is this useful?"
- "This is garbage" → stop. You've spent 8 hours, not 8 weeks.
- "Interesting but needs X" → proceed. Their feedback shapes skills.md.

---

### Phase 1 — Foundation

> **Goal:** Build the reusable core that every agent runs on. Prove the plugin architecture.
> **Time:** Weeks 1–2 | **Effort:** 24 hours

**1A — Agent runner**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 1.1 | Build `run_agent(agent_id, mission_brief, session)`: load manifest → load skills.md as system prompt → call LLM with filtered tools → handle tool loop → return structured output | 4h | 0.4 |
| 1.2 | Add model routing: read `model_tier` from manifest → route to configured model via OpenAI-compatible interface | 2h | 1.1 |
| 1.3 | Add tool filtering: read `requires_tools` from manifest → only pass matching MCP tools | 2h | 1.1 |

**1B — Agent registry**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 1.4 | Build `registry.py`: scan `/agents/*/manifest.json`, validate against available MCP tools, build registry dict | 2h | 1.1 |
| 1.5 | Define manifest.json Pydantic schema. All fields documented | 1h | 1.4 |
| 1.6 | Create `/agents/orchestrator/` with manifest.json + initial skills.md (20–30 heuristic patterns) | 3h | 1.4 |

**1C — Session & blackboard**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 1.7 | Build `session.py`: create session directory, state.json, conversations.md, evidence/ | 2h | — |
| 1.8 | Build `blackboard.py`: `append(author, type, content)` + `query(types, limit)` for filtered excerpts | 2h | 1.7 |

**1D — MCP client**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 1.9 | Build `mcp_client.py`: connect via stdio, `list_tools()`, `call_tool(name, params)`, timeout/retry handling | 3h | 0.2 |
| 1.10 | Add `includeSnapshot: false` optimization for non-read actions (saves 70–80% tokens per action) | 1h | 1.9 |

**1E — CLI**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 1.11 | Build `cli.py`: `qa-auto <url> [--prd] [--auth-cookie] [--browser] [--headless] [--budget]` | 2h | 1.1, 1.4, 1.7, 1.9 |

#### 🚦 Gate 1

Create a dummy `/agents/echo/` with manifest.json + skills.md. Does the registry discover it? Does `run_agent` execute it through the generic runner? If yes → plugin architecture works.

---

### Phase 2 — Discovery & planning

> **Goal:** Orchestrator crawls sites, builds site graphs, generates intelligent test plans.
> **Time:** Weeks 3–4 | **Effort:** 20 hours

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 2.1 | Add discovery instructions to orchestrator skills.md: systematic crawling, form detection, auth wall identification | 3h | 1.6 |
| 2.2 | Build `site_model.py`: pages[], forms[], nav_edges[], auth_boundaries[], api_endpoints[] | 3h | 2.1 |
| 2.3 | Add tech stack detection: React/Next.js/Stripe/JWT from DOM + network patterns | 2h | 2.2 |
| 2.4 | Expand skills.md with domain heuristics: login (8 patterns), checkout (12), search (5), nav (6), forms (10) | 4h | 2.1 |
| 2.5 | Add PRD ingestion: load via --prd flag, include in orchestrator context, add comparison instructions | 2h | 1.11 |
| 2.6 | Coverage map: compare test plan vs site graph → identify untested pages/forms | 2h | 2.2, 2.4 |
| 2.7 | Two-pass self-critique: orchestrator reviews plan for gaps using structured checklist | 2h | 2.4 |
| 2.8 | Build `tier1_locator.py`: parse snapshot → keyword match → score → return ref with confidence | 2h | 1.9 |

#### 🚦 Gate 2

Run on 5 real websites. Do site graphs capture all pages? Do test plans include heuristic-driven edge cases (not just happy paths)? If plans are shallow → invest more in skills.md before proceeding.

---

### Phase 3 — Execution & verification (MVP)

> **Goal:** Close the full loop. This is the hardest phase and produces the MVP.
> **Time:** Weeks 5–7 | **Effort:** 32 hours

**3A — Test generator agent**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 3.1 | Create `/agents/test_generator/` with manifest + skills.md (assertion templates, test data patterns) | 3h | 1.1 |
| 3.2 | Add `invoke_agent` tool to orchestrator: our code catches it, runs target agent, returns result | 3h | 1.1, 1.4 |
| 3.3 | Implement mission brief generation: PRD excerpt + page refs + blackboard + edge cases per invocation | 3h | 3.2, 2.5 |

**3B — Test execution**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 3.4 | Orchestrator executes test steps via Playwright MCP, collects snapshots + console + network per flow | 4h | 3.1, 3.2 |
| 3.5 | Inline execution for simple tests: orchestrator handles directly without invoking test_generator | 2h | 3.4 |
| 3.6 | Auth flows: cookie injection, storage state file, manual login with persisted context | 3h | 3.4 |

**3C — Verifier agent**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 3.7 | Create `/agents/verifier/` with manifest + skills.md (classification rules, bug report template) | 3h | 1.1 |
| 3.8 | Functional verification: assertions + actuals → PASS/FAIL/FLAKY/WARNING with confidence. Batch 5 per call | 3h | 3.7 |
| 3.9 | Visual verification: screenshots via vision-capable model on FAIL/WARNING only | 3h | 3.8 |
| 3.10 | Bug report generation: structured JSON with reproduction steps, expected/actual, evidence paths | 2h | 3.8 |

**3D — Report**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 3.11 | Final report: aggregate verdicts → report.json + report.md. Pass/fail counts, bug list, coverage stats, cost | 3h | 3.8, 3.10 |

#### 🚦 Gate 3 (CRITICAL)

Run on 3 real websites. For each:
1. Does the system catch at least 1 real bug a human would agree is a bug?
2. Is the false positive rate below 30%?
3. Is the report actionable (could a developer fix bugs from it alone)?

**If all pass → you have a working product. Everything after is enhancement.**

---

### Phase 4 — Quality & resilience

> **Goal:** Make it reliable on complex real-world sites. Reduce costs.
> **Time:** Weeks 8–9 | **Effort:** 24 hours

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 4.1 | Locator Tier 2: LLM fallback when Tier 1 confidence < 0.7 (vision-capable model + screenshot) | 3h | 2.8 |
| 4.2 | Shadow DOM, iframes, hover-reveal: detection patterns + retry logic | 3h | 4.1 |
| 4.3 | Retry logic: FLAKY verdicts auto-retry 3x with fresh context. Stability scoring | 2h | 3.8 |
| 4.4 | Context management: clear stale snapshots after extraction. 30–40% token reduction | 3h | 3.4 |
| 4.5 | Prompt caching: skills.md + PRD as cached prefix. Verify hits. 90% savings on repeated context | 2h | 2.5 |
| 4.6 | Sub-agent caching: skills.md cached across invocations within session | 1h | 4.5 |
| 4.7 | "Always include" negative patterns: console errors, mixed content, auth bypass, XSS in every input | 3h | 2.4 |
| 4.8 | Verifier feedback loop: per-site run history in site-models/{domain}.json. Enrich future runs | 3h | 3.11 |
| 4.9 | --browser flag: chromium/firefox/webkit. Cross-browser testing | 2h | 1.11 |
| 4.10 | --viewport flag: desktop/laptop/tablet/mobile. Responsive testing | 2h | 4.9 |

#### 🚦 Gate 4

Run on 3 complex SPAs (React, Next.js, Vue). For each:
1. Flaky rate < 10% after retries?
2. Cost < $4/run with caching enabled?
3. Cross-browser tests pass on chromium + at least one alternate engine?

---

### Phase 5 — MCP expansion

> **Goal:** Expand from ~60% to ~75% QA coverage via additional MCP servers and plugin agents.
> **Time:** Weeks 10–12 | **Effort:** 32 hours

**5A — Multi-MCP infrastructure**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 5.1 | Multi-MCP connection: mcp_client.py manages 2+ servers. Tools namespaced (playwright.*, jmeter.*) | 3h | 1.9 |
| 5.2 | API endpoint extraction: orchestrator logs network requests during discovery → filters to API endpoints | 2h | 2.2 |

**5B — JMeter MCP + load testing**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 5.3 | Research jmeter-mcp-server: install, connect, list tools, understand schemas | 2h | 5.1 |
| 5.4 | Create `/agents/load_tester/` (trigger: per_api_discovery). Skills: scenario templates, thresholds | 3h | 1.4, 5.3 |
| 5.5 | Load test execution: create plans from discovered endpoints, run scenarios, parse p50/p95/p99 | 3h | 5.4, 5.2 |

**5C — Postman MCP + API testing**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 5.6 | Research Postman MCP (official): connect, list tools | 2h | 5.1 |
| 5.7 | Create `/agents/api_tester/` (trigger: per_api_discovery). Skills: REST validation, schema checking | 3h | 1.4, 5.6 |
| 5.8 | API test execution: validate endpoints from discovery + PRD API specs | 2h | 5.7, 5.2 |

**5D — Security surface agent**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 5.9 | Create `/agents/security_tester/` (trigger: per_form_discovery). Skills: OWASP Top 10 surface checks | 3h | 1.4 |
| 5.10 | Security checks: XSS injection, header validation, auth bypass, open redirects | 2h | 5.9, 3.4 |

**5E — Observability correlation (optional)**

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 5.11 | Grafana MCP connection: connect if configured, list_datasources to discover what's available | 2h | 5.1 |
| 5.12 | Create `/agents/infra_observer/` (trigger: post_load_test). Skills: PromQL/LogQL/TraceQL correlation patterns | 3h | 5.11 |
| 5.13 | Sentry MCP connection: OAuth via mcp.sentry.dev or stdio for self-hosted | 2h | 5.1 |
| 5.14 | Create `/agents/error_observer/` (trigger: post_execution). Skills: error correlation, severity triage | 2h | 5.13 |

#### 🚦 Gate 5

Run the full system on a real product with a real PRD. Present to a QA engineer or engineering lead. Ask: "Would you trust this enough to reduce manual testing?" Their answer determines Phase 6 scope.

---

### Phase 6 — Integration & productization

> **Goal:** Production-ready, CI/CD integrated, usable by people other than you.
> **Time:** Weeks 13–15 | **Effort:** 24 hours

| ID | Task | Effort | Deps |
|----|------|--------|------|
| 6.1 | GitHub Action: trigger on PR/push, run qa-auto, post results as PR comment | 4h | 3.11 |
| 6.2 | Webhook mode: `qa-auto serve --port 8080`. POST /run → QA session → results | 3h | 1.11 |
| 6.3 | Incremental testing: diff site graph vs previous → test only changed pages (50–70% cost reduction) | 3h | 2.2, 4.8 |
| 6.4 | HTML report: self-contained, embedded screenshots, filterable by verdict/severity | 4h | 3.11 |
| 6.5 | Jira/Linear/GitHub Issues integration: auto-create tickets for FAIL verdicts | 3h | 3.10 |
| 6.6 | Cost tracking: per-session token usage by agent, running total, budget cap alerts | 2h | 3.11 |
| 6.7 | Config validation & documentation: schema validation for qa-auto.yaml, example config with annotated defaults | 2h | 1.11 |
| 6.8 | Watch mode: re-run on schedule or webhook trigger. Continuous monitoring | 3h | 6.2 |

#### 🚦 Gate 6

Deploy GitHub Action on a real repo PR. Verify:
1. Action triggers, runs qa-auto, and posts results as PR comment?
2. HTML report renders correctly with embedded screenshots?
3. Jira/Linear ticket auto-created for at least one FAIL verdict?

---

## Dependency graph (critical path)

```
0.4 → 1.1 → 1.4 → 2.1 → 2.4 → 3.1 → 3.4 → 3.8 → 3.11
                                  ↓
                                skills.md quality determines EVERYTHING downstream
```

Every task on this path is a blocker. Tasks off the critical path (cross-browser, Grafana, Sentry) can be deferred without blocking progress. Invest time in skills.md heuristics (2.4) — weak heuristics produce weak tests regardless of how good the infrastructure is.

---

## Cost optimization checklist

Apply in Phase 4, but design for from Phase 1:

- [ ] `includeSnapshot: false` on non-read actions (1.10) — 70–80% savings per action
- [ ] Clear stale snapshots from context after extraction (4.4) — 30–40% of orchestrator input
- [ ] Prompt caching for skills.md + PRD (4.5) — 90% on repeated context
- [ ] Batch verifier calls: 5 verdicts per call instead of 1 (3.8) — 40→8 calls
- [ ] Visual verification only on FAIL/WARNING (3.9) — avoid 5–8K tokens per screenshot on passes
- [ ] Incremental testing on repeat runs (6.3) — 50–70% cost reduction
- [ ] Tier 1 locator handles 80% of element finding at $0 cost (2.8)
- [ ] Inline execution for simple tests (3.5) — avoids sub-agent overhead
- [ ] Route utility agents to cheaper model tier when available (1.2)
- [ ] Per-session budget cap, abort gracefully (6.6)

---

## Manifest schema

```json
{
  "id": "security_tester",
  "name": "Security Surface Tester",
  "version": "1.0.0",
  "type": "tester",
  "trigger": "per_form_discovery",
  "requires_tools": [
    "playwright.browser_type",
    "playwright.browser_snapshot",
    "playwright.browser_console_messages"
  ],
  "model_tier": "sub",
  "input_format": "mission_brief_markdown",
  "output_format": "findings_json",
  "description": "OWASP Top 10 surface checks on discovered forms"
}
```

**Trigger types:**
- `on_demand` — orchestrator invokes explicitly
- `per_page_discovery` — fires for each new page discovered
- `per_form_discovery` — fires for each form discovered
- `per_api_discovery` — fires when API endpoints discovered
- `post_execution` — fires after test execution completes
- `post_load_test` — fires after load tester completes

---

## Testing coverage matrix

| Testing type | AI coverage | MCP server | Phase |
|-------------|------------|------------|-------|
| Smoke testing | 95% | Playwright | 3 |
| Sanity testing | 95% | Playwright | 3 |
| Regression testing | 90% | Playwright | 3 |
| End-to-end testing | 90% | Playwright | 3 |
| Cross-browser | 85% | Playwright | 4 |
| Responsive design | 85% | Playwright | 4 |
| API testing | 85% | Postman | 5 |
| Boundary/edge case | 80% | Playwright | 3 |
| Visual regression | 80% | Playwright | 3 |
| Integration testing | 75% | Playwright | 3 |
| Load/stress testing | 70% | JMeter | 5 |
| Performance (client) | 65% | Playwright + JMeter | 5 |
| Localization | 50% | Playwright | Future |
| Security (surface) | 50% | Playwright + Postman | 5 |
| Accessibility | 45% | Playwright | Future |
| UAT | 40% | Playwright | 3 |
| Exploratory | 35% | Playwright | 3 |
| Usability | 0% | N/A | Never (human) |

**Overall: ~60% with Playwright only → ~75% with all MCP servers**

---

## Competitive landscape

| Competitor | What they do | What we do differently |
|-----------|-------------|----------------------|
| **Bug0** ($250–2500/mo) | AI agents + human FDE. Browser E2E. Self-healing. Playwright-based. | We add load testing, API testing, infra/error correlation, PRD-driven planning. Self-hosted. |
| **QA.tech** | AI learns site, autonomous regression. SaaS. | We add multi-agent architecture, plugin registry, observability integration. |
| **mabl** | AI-enhanced test automation. Enterprise. Strong product. | mabl requires defining flows. We discover autonomously. We add performance/API/security. |
| **Functionize** | Enterprise AI test automation. Self-healing. | Similar to mabl comparison. We're open/self-hosted, they're SaaS. |
| **OpenObserve "Council"** | Multi-agent with Claude Code. Internal tool. | Most architecturally similar. But no MCP, no load testing, no observability correlation, not general-purpose. |
| **Spur** | E-commerce specific. Autonomous agents. | We're general-purpose. They're vertical. |

**Our actual moat:** Nobody unifies functional testing + load testing + API testing + infrastructure correlation + application error correlation into one AI-orchestrated system. Everyone else does one piece.

---

## Getting started

### Prerequisites

```bash
# Python 3.11+
python --version

# Node.js (for Playwright MCP)
node --version

# LLM API key (Gemini for prototyping, Anthropic for later phases)
export GEMINI_API_KEY="AIza..."
# export ANTHROPIC_API_KEY="sk-ant-..."  # later phases
```

### Phase 0 — Quick start

```bash
# Clone and setup
git clone <repo-url> && cd autonomous-qa
python -m venv .venv && source .venv/bin/activate
pip install google-genai mcp pydantic pyyaml

# Verify Playwright MCP works
npx @playwright/mcp@latest --headless
# Should print available tools, then Ctrl+C

# Run the proof of concept
python src/phase0.py https://example.com
```

### Phase 1+ — Full setup

```bash
pip install -e ".[dev]"
cp qa-auto.example.yaml qa-auto.yaml
# Edit qa-auto.yaml with your settings

qa-auto https://staging.myapp.com --prd ./requirements.md
```

---

## Definition of done (per phase)

| Phase | Done when... |
|-------|-------------|
| 0 | Script runs on 3 sites, produces readable output, stays within free-tier limits |
| 1 | `qa-auto <url>` launches, connects to MCP, runs orchestrator, new agents discoverable by folder |
| 2 | Site graph captures all pages on 5 test sites, plans include heuristic-driven edge cases |
| 3 | Full session produces report with real bugs, false positive rate < 30%, report is actionable |
| 4 | Handles complex SPAs, flaky rate < 10% after retries, cost < $4/run with caching, cross-browser passes |
| 5 | Load tests run on discovered APIs, API endpoints validated, security checks find issues on test sites, Grafana/Sentry correlation works when configured |
| 6 | GitHub Action runs on PR, HTML report renders, Jira ticket created for FAIL, cost tracked |

---

## License

TBD

---

*Built by Amitabh | April 2026*
