# Dev Session 3 — Summary
**Date:** 2026-04-09
**Presentation deadline:** Tuesday 2026-04-15

---

## What we built today

This session focused on **skills.md quality across all agents**, a **comprehensive
HTML report template**, **cost calculation correctness**, and **infrastructure fixes**
for running on a new Windows machine.

---

### 1. TestGen skills.md — Full rewrite (four-pillar model)

`agents/test_generator/skills.md` was completely rewritten to align with the four
standard pillars of web testing.

**New pillars added:**

| Pillar | What it tests |
|--------|---------------|
| Functional (existing) | Feature correctness — login, forms, search, navigation, cart |
| Compatibility (NEW) | Cross-viewport with `browser_resize` to 375px; tech-stack-specific compat checks |
| Accessibility (NEW) | Accessibility tree checks — missing alt text, unlabelled inputs, missing `<h1>`, missing `lang`, keyboard navigation via `browser_press_key` |
| Progressive Enhancement (NEW) | HTML5 form attributes, JS-disabled fallback observations |

**Schema additions to every finding:**
- `pillar` — required, one of the four pillars above
- `viewport` — `desktop` | `mobile` | `tablet` (defaults to `desktop`)
- `evidence.accessibility_tree_excerpt` — for a11y findings, paste the relevant accessibility tree snippet

**`session_summary` additions:**
- `pillars_covered` — array of which pillars produced findings

**`skipped` in capped output** now organised by pillar so the orchestrator can write a targeted retry brief.

**Quality fixes:**
- Console noise: only ERROR/WARN level recorded (not all messages)
- SQL error detection: explicit signatures listed (`ORA-`, `SQLSTATE`, `mysql_fetch_array`, `You have an error in your SQL syntax`, etc.)
- Screenshot file-path convention removed — agent can't write files; describes what it sees in `observed` instead

**Manifest updated:** `browser_resize` and `browser_press_key` added to `requires_tools`.

---

### 2. Crawler skills.md — Full rewrite (v2.0)

`agents/crawler/skills.md` was completely rewritten. The Crawler is now the
enrichment layer for the entire four-pillar pipeline.

**Key changes:**

**Priority-ordered crawl plan (new)**
Before crawling, the Crawler builds an ordered plan: critical → high → normal → low.
Critical pages (login, checkout, dashboard) are always visited first. Footer legal
pages are always last. The 15-page cap (reduced from 20) is intentional — richer
per-page work beats shallow breadth.

**Page classification (new)**
Every page gets a `page_type` (one of 12 values: `home`, `login`, `signup`,
`dashboard`, `listing`, `detail`, `form`, `checkout`, `content`, `legal`, `error`,
`other`) and a `priority`. TestGen uses these to sequence its test plan.

**Accessibility hints per page (new)**
```json
"accessibility_hints": {
  "has_title": true,
  "has_h1": true,
  "h1_count": 1,
  "has_lang_attribute": true,
  "images_total": 12,
  "images_missing_alt": 2,
  "inputs_missing_labels": 0,
  "landmark_regions": ["banner", "navigation", "main", "contentinfo"],
  "skip_link_present": false
}
```

**Compatibility hints per page (new)**
```json
"compatibility_hints": {
  "has_viewport_meta": true,
  "viewport_meta_content": "width=device-width, initial-scale=1",
  "has_responsive_indicators": true,
  "uses_iframes": false,
  "uses_canvas": false,
  "uses_video": false,
  "noscript_present": false,
  "js_required_for_content": false
}
```

**Expanded form schema (new)**
Each form field now records: `input_type`, `required`, `placeholder`, `has_label`.
Top-level form fields added: `purpose`, `submit_button_text`, `submits_to`.

**Template detection (new)**
Crawler detects URL patterns that are template variants (`/products/{slug}`) and
visits only one example. Saves budget for important pages.
```json
"templates_detected": [{"pattern": "/products/{slug}", "sampled_url": "..."}]
```

**`discovery_notes[]` (new)**
Free-text observations that don't fit structured fields: cookie banners, auth
bypasses, broken nav links. TestGen reads these before testing.

**Retry-aware behavior (new)**
Explicit section for handling `## Retry context` briefs — skips already-captured
pages, visits only the retry list, sets a smaller iteration target.

**Manifest changes:**
- Version 1.0.0 → 2.0.0
- `max_iterations` 50 → 60
- `max_output_tokens` 8192 → 16384
- `browser_run_code` added to `requires_tools`

---

### 3. ReportGen skills.md — Fixed HTML template

`agents/report_generator/skills.md` was rewritten with a **fixed HTML template**
approach. The agent no longer generates HTML from scratch — it copies the template
and fills `{{PLACEHOLDER}}` markers with real data.

**New template sections:**

| Section | Description |
|---------|-------------|
| Grade badge (A/B/C/D) | Derived from severity counts. A=clean, B=low/medium only, C=high, D=critical. Displayed in header. |
| Executive Summary | Risk chip (Low/Medium/High/Critical) + LLM-written narrative paragraph + key stat counts |
| Run Health banner | Unchanged from session 2 (3 cases: complete/recovered/incomplete) |
| Severity breakdown | Horizontal CSS bars — computed as `round((count/max)*100)%`. Simpler and more reliable than SVG rects. |
| Coverage by pillar | 4 mini cards: Functional / Accessibility / Compatibility / Progressive Enhancement, each showing test count and issue count |
| Critical issues spotlight | Top 3 critical/high findings as callout cards. Entire section omitted if no critical/high findings. |
| All Findings | CSS-grid rows using `<details>` for expansion. Expanded view shows: numbered steps to reproduce, Expected vs Observed side-by-side (green/red top border), verifier reasoning in a purple box, collapsible evidence sections (console, network, a11y tree), tags |
| Pages tested | Unchanged |
| Tech stack | Pill badges |
| Test coverage | Pass/skip items per category |
| Invocation timeline | Collapsible, unchanged from session 2 |

**Fill guide:**
Every `{{PLACEHOLDER}}` has an explicit data source and example in the fill guide.
Complex fragments (findings rows, severity bars, pillar cards) have exact HTML
patterns to copy with computed values substituted.

**Bug fixes in previous version:**
- `WARNING` verdict removed everywhere — Verifier produces `INCONCLUSIVE`, not `WARNING`
- Findings table now shows ALL verdicts (not just FAIL/FLAKY) — PASS rows are visible
- Critical spotlight only rendered if critical/high findings exist

**Print stylesheet** added so the report renders cleanly on paper.

---

### 4. Orchestrator skills.md — Schema fixes

Fixed the `TestGen` expected output schema in the orchestrator's mission brief
template. The previous template showed:
- `"summary"` → now `"session_summary"`
- `"tests_executed"` → now `"tests_attempted"`
- `"tech_stack"` → now `"tech_stack_observed"`
- Finding IDs `"F001"` → `"f001"` (lowercase)
- `"reproduction_steps"` → `"steps_taken"`
- `"actual"` → `"observed"`

(Session interrupted before completing Verifier schema fix — still pending.)

**TestGen input section updated** to describe all new Crawler v2 `site_map` fields
and how to use them (`page_type` and `priority` for sequencing, `accessibility_hints`
as a11y pillar starting points, `discovery_notes` read first).

---

### 5. Cost logic fixes (`src/token_usage.py`)

**Bug 1 — Wrong Opus 4.5 pricing:**
`"claude-opus-4"` was returning `$15/$75` per million tokens (old Opus 3 rate).
Correct rate for Opus 4.5 is `$5/$25`. Fixed by adding more specific keys before
general ones (dict order matters for substring matching).

**Bug 2 — All agents billed at same rate:**
The orchestrator uses Opus; sub-agents use Sonnet. Previously all tokens were
calculated at Opus rates, overcharging sub-agents by ~67%.

Fix: `TokenUsage` now accepts a `sub_model` parameter. `agent_cost_usd()` applies
Opus pricing for `agent_id == "orchestrator"` and Sonnet pricing for all sub-agents.
`estimated_cost_usd` now sums per-agent costs rather than applying one rate to total.

`cost.json` `pricing` block now shows both models and their rates:
```json
"pricing": {
  "orchestrator": {"model": "claude-opus-4-5...", "input_per_M_usd": 5.0, "output_per_M_usd": 25.0},
  "sub_agents":   {"model": "claude-sonnet-4-5...", "input_per_M_usd": 3.0, "output_per_M_usd": 15.0}
}
```

**Updated pricing table:**
```
claude-opus-4-6/4-5/4:   $5 / $25 per MTok
claude-sonnet-4-6/4-5/4: $3 / $15 per MTok
claude-haiku-4-5/4:      $1 / $5 per MTok
claude-3-5-sonnet:       $3 / $15 per MTok
claude-3-5-haiku:        $0.80 / $4 per MTok
claude-3-opus:           $15 / $75 per MTok
```

---

### 6. Session folder logic (`src/main.py`)

Each run now creates a timestamped subfolder under `sessions/`:
```
sessions/
  20260409_110059_practicetestautomation/
    report.html
    report.md
    findings.json
    verdicts.json
    site_map.json
    raw_conversation.json
    cost.json
  20260409_143212_toscrape/
    ...
```

Format: `YYYYMMDD_HHMMSS_hostname` — chronologically sortable, human-readable.
Previous runs are no longer overwritten.

---

### 7. Windows machine setup

Got the tool running on a new company Windows machine (no admin access). Key fixes:

**`npx` → `npx.cmd` on Windows:**
On Windows, npm/npx commands are `.cmd` wrappers. Python `subprocess` can't find
plain `npx` on Windows. Fixed in `src/main.py`:
```python
npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
```

**AWS credentials without admin access:**
AWS CLI can't be installed without admin rights. Solution: `pip install awscli`
(installs into the venv without elevation) or create `~/.aws/credentials` manually
via Notepad. The `.env` approach also works since `load_dotenv()` is already wired
in `cli.py`.

---

## Current codebase state

```
qa/
├── src/
│   ├── main.py          — timestamped session subfolder per run; npx.cmd on Windows;
│   │                      TokenUsage(model=..., sub_model=...)
│   ├── token_usage.py   — fixed pricing table; per-agent pricing split (Opus/Sonnet);
│   │                      sub_model param; pricing block in cost.json shows both models
│   ├── runner.py        — unchanged from session 2
│   ├── config.py        — unchanged from session 2
│   ├── prompts.py       — unchanged
│   ├── tools.py         — unchanged
│   └── cli.py           — unchanged (load_dotenv() already wired)
│
├── agents/
│   ├── orchestrator/    — skills.md: TestGen mission brief template schema fixed;
│   │                      TestGen input section updated for Crawler v2 fields
│   ├── crawler/         — FULL REWRITE v2.0: priority-ordered crawl, page_type,
│   │                      accessibility_hints, compatibility_hints, expanded forms,
│   │                      template detection, discovery_notes, retry-aware behavior
│   │                      manifest.json: v2.0, max_iterations=60, max_output_tokens=16384,
│   │                      browser_run_code added
│   ├── test_generator/  — FULL REWRITE: four-pillar model (functional/compatibility/
│   │                      accessibility/progressive_enhancement); new fields: pillar,
│   │                      viewport, evidence.accessibility_tree_excerpt, pillars_covered;
│   │                      SQL error signatures; console noise filtering; screenshot fix
│   │                      manifest.json: browser_resize, browser_press_key added
│   ├── verifier/        — skills.md: unchanged from session 2 (schema update pending)
│   └── report_generator/ — FULL REWRITE: fixed HTML template with {{PLACEHOLDER}} fill
│                           guide; grade badge; executive summary; severity bars (CSS);
│                           pillar cards; critical spotlight; collapsible findings with
│                           reproduction steps + expected/observed + reasoning + evidence
```

---

## What is NOT done yet

- **Verifier skills.md schema update** — needs to handle new `pillar`, `viewport`,
  `evidence.accessibility_tree_excerpt` fields from TestGen. Classification logic
  unchanged; needs to preserve new fields in verdicts and reference them in reasoning.
- **Orchestrator Verifier mission brief template** — still shows wrong schema
  (`findings` vs `verdicts`, `confidence: 0.95` vs `"high"`, `WARNING` vs `INCONCLUSIVE`).
  Interrupted during session.
- **ReportGen → Verifier schema alignment** — ReportGen needs to join `verdicts` +
  `findings` by `finding_id` to get descriptive fields. The `{{FINDINGS_ROWS}}`
  fill guide covers this but hasn't been tested end-to-end.
- **End-to-end validation run** — no full run completed on this machine yet (AWS
  credentials still being configured). Validation checklist:
  - `quotes.toscrape.com` — verify Crawler v2 produces clean `accessibility_hints`
  - `demoqa.com` — verify expanded form schema (diverse `input_type` values)
  - `practicetestautomation.com` — original target; verify full pipeline
- **Presentation sites** — not yet run on the actual presentation target site(s)
- **README** — still describes the old architecture; not updated this session

---

## Next likely tasks

1. Fix Verifier skills.md to handle new pillar/viewport fields from TestGen
2. Fix Orchestrator's Verifier mission brief template schema
3. Get AWS credentials working on the company machine and run end-to-end
4. Validate Crawler v2 output on toscrape.com and demoqa.com
5. Run on the presentation target site and verify the HTML report renders correctly
6. README rewrite (low priority until pipeline is stable)
