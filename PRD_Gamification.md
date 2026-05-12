# Product Requirements Document
## HealthQuest — Health Gamification MCP Server

**Version:** 1.0  
**Date:** May 2026  
**Status:** Draft  

---

## 1. Overview

### 1.1 Product Summary

HealthQuest is a FastMCP server that transforms raw health lab data (from PDFs or JSON) into a gamified, interactive health improvement experience. It exposes a suite of MCP tools powered by Prefab UI that render interactive dashboards, organ-level parameter panels, trend charts, and AI-generated recommendations — all rendered natively inside MCP-compatible AI clients (Claude, ChatGPT, VS Code, Goose).

### 1.2 Problem Statement

Lab reports are dense, clinical, and passive. Users receive a PDF, glance at red/green flags, and don't know what to do next. There's no feedback loop, no motivation to improve, and no translation of biomarkers into actionable lifestyle changes. Health data sits unused.

### 1.3 Vision

Make health data feel like a game. Each biomarker is a stat. Each organ system is a quest zone. Each improvement is XP. The user levels up their body the way they'd level up a character — with clear goals, visible progress, and rewards for effort.

---

## 2. Goals & Non-Goals

### Goals
- Parse and ingest lab data from structured JSON or extracted PDF text
- Group biomarkers by organ system (Liver, Kidney, Heart, Blood, Thyroid, etc.)
- Render interactive Prefab UI charts and dashboards inside MCP clients
- Compute a gamified Health Score (XP, Level, Rank) per organ and overall
- Surface AI-generated, personalized recommendations (diet, exercise, supplements, products)
- Support multiple reports over time for trend tracking
- Be fully self-contained as a FastMCP server; no frontend infrastructure required

### Non-Goals
- Direct integration with wearable devices or EHR systems (v2)
- User authentication / multi-user persistence (v2)
- Prescription or clinical diagnosis (explicitly out of scope — always)
- Native mobile app (MCP client handles the host layer)

---

## 3. Users

| Persona | Description |
|---|---|
| **Health-conscious individual** | Uploads their annual lab report, wants to understand what it means and what to do |
| **Fitness optimizer** | Tracks biomarkers over multiple tests, wants to see trends and optimize performance |
| **Developer / power user** | Connects the MCP server to their own AI client workflow, extends or embeds it |

---

## 4. Technical Architecture

### 4.1 Stack

| Layer | Technology |
|---|---|
| MCP Server Framework | FastMCP v3.2+ |
| UI Component Library | Prefab UI (`prefab-ui`, pinned version) |
| PDF Parsing | `pdfplumber` or `pymupdf` |
| AI Recommendations | Anthropic Claude API (via `anthropic` SDK) |
| Data Validation | Pydantic v2 |
| Runtime | Python 3.11+ |
| Transport | `stdio` (local) or `streamable-http` (hosted) |

### 4.2 Server Structure

```
healthquest/
├── server.py               # FastMCP entry point, mounts all apps
├── core/
│   ─── models.py           # Pydantic models: LabResult, Parameter, OrganPanel
│   ─── parser.py           # JSON + PDF ingestion and normalization
│   ─── scorer.py           # Health score, XP, level computation
│   ─── organs.py           # Organ-to-parameter mapping registry
├── apps/
│   ─── ingest.py           # Tool: upload_report (PDF or JSON)
│   ─── dashboard.py        # Tool: show_health_dashboard (overall gamified view)
│   ─── organ_panel.py      # Tool: show_organ_panel (per-organ deep dive)
│   ─── charts.py           # Tools: show_trend_chart, show_radar_chart, show_gauge_chart
│   ─── recommendations.py  # Tool: get_recommendations (AI-generated)
│   ─── quests.py           # Tool: show_active_quests (actionable goals)
├── agent/
│   ─── runner.py           # run_health_agent — outer @mcp.tool(app=True) entry point
│   ─── loop.py             # Claude tool-use loop; dispatches agent tools; collects UI blocks
│   ─── tools.py            # 5 agent tools: prioritize_organs, get_params_by_organ,
│   │                       #   get_recommendations_for_case, build_organ_ui_section, finish_dashboard
│   ─── prompts.py          # Agent system prompt + dynamic user prompt builder
│   ─── assembler.py        # Merges UI section blocks into final PrefabApp
│   ─── compare.py          # Tool: compare_reports (multi-report diff)
└── data/
    ─── organ_map.json       # Parameter → organ system mapping
    ─── reference_ranges.json # Normal ranges per parameter (age/sex adjusted)
    ─── products.json        # Curated supplement/product recommendations per flag
```

### 4.3 Data Flow

```
User uploads PDF / JSON
        ↓
parser.py → normalized LabResult (list of Parameters with values + ranges)
        ↓
scorer.py → Health Score, XP per organ, overall Level and Rank
        ↓
FastMCPApp tools → Prefab UI rendered in MCP client
        ↓
Claude API → personalized recommendations per flagged parameter
```

---

## 5. MCP Tools Specification

### 5.1 Data Ingestion

#### `upload_report`
- **Type:** `@mcp.tool` (no UI, returns structured data)
- **Input:** `file_path: str` (PDF) OR `data: list[dict]` (JSON)
- **Output:** Parsed and normalized `LabResult` stored in session state; returns a summary string with parameter count, date, and any parse warnings
- **Logic:**
  - PDF: extract text via `pdfplumber`, regex-parse parameter/value/range triplets
  - JSON: validate against `LabResult` Pydantic schema
  - Normalize units; flag out-of-range values; map each parameter to an organ system

---

### 5.2 Dashboard Tools (Prefab UI)

#### `show_health_dashboard`
- **Type:** `@app.ui()` entry point
- **Input:** None (uses session state from last upload)
- **UI Components:**
  - **Header Card:** User rank badge (e.g. "🥈 Silver Health Champion"), overall Health Score out of 1000, XP progress bar to next level
  - **Organ Score Grid:** `Grid(columns=3)` — one `Card` per organ system showing organ name, emoji icon, score out of 100, and a color-coded `Badge` (Optimal / Good / At Risk / Critical)
  - **Quick Stats Row:** Total parameters checked, parameters in range, parameters flagged, date of report
  - **Active Quests Preview:** Top 3 recommended actions as compact `Badge` items with a "View All" `Button` that opens `show_active_quests`
- **Gamification:**
  - Overall score = weighted average of organ scores
  - Level thresholds: 0–399 Bronze, 400–599 Silver, 600–799 Gold, 800–949 Platinum, 950–1000 Diamond
  - XP to next level displayed as animated progress bar

#### `show_organ_panel`
- **Type:** `@app.ui()` entry point
- **Input:** `organ: str` (e.g. "liver", "kidney", "thyroid")
- **UI Components:**
  - **Organ Hero Card:** Organ name + icon, score, rank badge, short AI-generated health summary (1–2 sentences)
  - **Parameter Table:** `DataTable` with columns: Parameter, Value, Normal Range, Status (color-coded badge), Delta from midpoint
  - **Gauge Charts:** One `GaugeChart` per out-of-range parameter, showing value relative to min/max range
  - **Recommendations Section:** Tabbed panel — Diet / Exercise / Supplements / Products — populated by AI
- **Supported Organs:** Liver, Kidney, Heart, Blood (CBC), Thyroid, Metabolic, Hormones, Vitamins & Minerals

---

### 5.3 Chart Tools (Prefab UI)

#### `show_trend_chart`
- **Type:** `@mcp.tool(app=True)`
- **Input:** `parameter: str`, `reports: list[LabResult]` (requires multiple uploads)
- **UI:** `LineChart` with date on X-axis, value on Y-axis; reference range rendered as a shaded band; data points color-coded (green = in range, red = out of range); `Badge` showing trend direction (↑ Improving / ↓ Declining / → Stable)
- **Fallback:** If only one report exists, shows a single-point `BarChart` with range context and a prompt to upload another report for trend tracking

#### `show_radar_chart`
- **Type:** `@mcp.tool(app=True)`
- **Input:** `organ: str` (optional; defaults to all organs)
- **UI:** `RadarChart` with one axis per organ or per parameter within an organ; normalized 0–100 scores; overlays two datasets if comparing reports
- **Use case:** Holistic "body map" view — strengths and gaps at a glance

#### `show_gauge_chart`
- **Type:** `@mcp.tool(app=True)`
- **Input:** `parameter: str`
- **UI:** Single large `GaugeChart` for one parameter; shows current value, normal range band, optimal zone; color transitions from red → yellow → green; numeric readout with unit

#### `show_bar_comparison`
- **Type:** `@mcp.tool(app=True)`
- **Input:** `organ: str`
- **UI:** Horizontal `BarChart` — all parameters for the organ, bars colored by status; reference range rendered as a vertical marker line per bar; sorted by deviation from optimal (worst first)

---

### 5.4 Recommendation Tools

#### `get_recommendations`
- **Type:** `@app.tool()` (backend, called by UI via `CallTool`)
- **Input:** `organ: str`, `flagged_parameters: list[str]`
- **Output:** Structured JSON with four keys: `diet`, `exercise`, `supplements`, `products` — each a list of recommendation objects `{title, description, priority, links?}`
- **Logic:** Calls Claude API with a structured prompt containing the flagged parameters, their values, and the reference ranges. Returns parsed JSON.
- **Caching:** Results cached per `(organ, frozenset(flagged_parameters))` in session to avoid redundant API calls

#### `get_product_recommendations`
- **Type:** `@mcp.tool` (text output, no UI)
- **Input:** `parameter: str`, `direction: "high" | "low"`
- **Output:** List of curated supplement/product suggestions with reasoning, dosage notes, and a disclaimer
- **Data source:** `products.json` lookup first; Claude API for parameters not in the static list
- **Disclaimer:** Always appended — "These are general wellness suggestions, not medical advice. Consult a healthcare provider."

---

### 5.5 Quest System Tools

#### `show_active_quests`
- **Type:** `@app.ui()` entry point
- **UI Components:**
  - **Quest Cards:** One `Card` per active quest; each card shows: Quest name (e.g. "Boost Your Vitamin D"), organ tag badge, difficulty badge (Easy / Medium / Hard), XP reward, and a short action description
  - **Progress Tracker:** `ProgressBar` showing quests completed vs total across all uploads
  - **Completed Quests:** Collapsible section showing parameters that normalized between reports
- **Quest Generation Logic:**
  - One quest per out-of-range parameter
  - Priority: Critical > At Risk > Borderline
  - Quest content drawn from `get_recommendations` AI output
  - Difficulty = deviation from range: <20% = Easy, 20–50% = Medium, >50% = Hard
  - XP reward = difficulty × 10

---

### 5.6 Multi-Report Tools

#### `compare_reports`
- **Type:** `@mcp.tool(app=True)`
- **Input:** `report_a: LabResult`, `report_b: LabResult`
- **UI:**
  - **Summary Cards:** Parameters improved, worsened, stable — color-coded counts
  - **Delta Table:** `DataTable` with columns: Parameter, Report A value, Report B value, Change (↑/↓/→), Status change
  - **Radar Overlay:** `RadarChart` with both reports overlaid, showing progress

---

## 6. Agentic Analysis Loop

This is the core intelligence layer of HealthQuest. Rather than having the user manually call individual tools, a single entry-point tool — `run_health_agent` — spins up an internal Claude agent that autonomously decides what to look at, in what order, and builds the final UI from its findings.

### 6.1 How the Agent Loop Works

```
User calls: run_health_agent(context="I want to focus on weight loss")
                    ↓
Agent (Claude) receives: all lab data summary + user context + 4 agent tools
                    ↓
         ┌──────────────────────────────────────────┐
         │            AGENT TOOL LOOP               │
         │                                          │
         │  1. prioritize_organs()                  │
         │     → decides order: Metabolic first,    │
         │       then Liver, then Blood             │
         │                                          │
         │  2. get_params_by_organ("metabolic")     │
         │     → exact values + dates for all       │
         │       metabolic parameters               │
         │                                          │
         │  3. get_recommendations_for_case(        │
         │       organ="metabolic",                 │
         │       use_case="weight loss",            │
         │       flagged=["HbA1c", "Glucose"])      │
         │     → targeted diet/exercise/supplement  │
         │       advice for that specific goal      │
         │                                          │
         │  4. build_organ_ui_section(              │
         │       organ="metabolic",                 │
         │       params=..., recs=...)              │
         │     → writes + executes Prefab Python    │
         │       code, returns a rendered UI block  │
         │                                          │
         │  (repeats steps 2–4 for each organ       │
         │   in priority order)                     │
         └──────────────────────────────────────────┘
                    ↓
         Agent assembles all UI blocks into one
         final PrefabApp and returns it to the user
```

The agent runs using the Anthropic SDK's tool-use loop directly inside the FastMCP tool handler. It is **not** exposed to the outer MCP client's model — it's a private agentic subprocess. The outer MCP client (Claude Desktop, ChatGPT, etc.) only sees the final rendered `PrefabApp`.

### 6.2 Entry Point Tool

#### `run_health_agent`
- **Type:** `@mcp.tool(app=True)` — the outer shell that the host model calls
- **Input:**
  - `context: str` — optional free-text user goal or focus (e.g. "I care most about energy levels", "I'm trying to lose weight", "preparing for a marathon")
  - `report_ids: list[str]` — optional list of specific report IDs to analyze; defaults to the most recent upload
- **Output:** `PrefabApp` — a fully assembled, multi-section interactive dashboard built by the agent
- **Behavior:**
  1. Loads all lab data from session state
  2. Constructs the agent system prompt (see §6.6)
  3. Runs the internal Claude tool loop until the agent signals `done`
  4. Collects all `build_organ_ui_section` outputs in priority order
  5. Wraps them in a top-level `PrefabApp` with a header and XP summary

---

### 6.3 Agent Tool: `prioritize_organs`

**Purpose:** The agent calls this first to decide which organ systems matter most given the user's data and context. It returns an ordered list — not a fixed ranking, but a reasoned prioritization based on severity of flags, user's stated goal, and clinical interdependencies (e.g. if metabolic markers are bad, liver often follows).

**Schema:**
```python
def prioritize_organs(
    context: str,           # user's stated goal/focus
    all_organ_summaries: list[OrganSummary]  # pre-computed scores + flag counts
) -> list[OrganPriority]:
    """
    Returns organs in the order the agent should investigate,
    with a brief reasoning string for each.
    """
```

**Output shape:**
```json
[
  { "organ": "metabolic", "priority": 1, "reason": "HbA1c is elevated; directly relevant to user's weight loss goal" },
  { "organ": "liver",     "priority": 2, "reason": "SGOT borderline high; often linked to metabolic dysfunction" },
  { "organ": "blood",     "priority": 3, "reason": "Hemoglobin slightly low; may explain fatigue" }
]
```

**Implementation:** This is a pure Python function registered as a tool on the internal agent client. It does not call Claude again — it's a structured data transform that the agent's tool loop invokes like any other function. The agent's own reasoning (from Claude) produces the prioritization; this tool just validates and formats it.

---

### 6.4 Agent Tool: `get_params_by_organ`

**Purpose:** Returns all parameter values and their test dates for a given organ system. This is the agent's data-fetching tool — it gives Claude the exact numbers it needs to reason about, rather than sending everything upfront in the context window.

**Schema:**
```python
def get_params_by_organ(
    organ: str,                    # e.g. "liver", "metabolic", "blood"
    report_ids: list[str] | None   # None = all uploaded reports
) -> OrganData:
    """
    Fetch all parameters, their values, reference ranges,
    and result dates for the specified organ system.
    """
```

**Output shape:**
```json
{
  "organ": "liver",
  "parameters": [
    {
      "name": "SGOT",
      "unit": "U/L",
      "reference_range": { "min": 0.0, "max": 31.0 },
      "readings": [
        { "date": "2025-10-15", "value": 27.76, "status": "normal" },
        { "date": "2025-06-10", "value": 34.2,  "status": "high" }
      ],
      "trend": "improving",
      "deviation_pct": null
    }
  ],
  "organ_score": 82,
  "flagged_count": 0
}
```

**Design note:** Readings are always returned in descending date order (most recent first). If only one report exists, `trend` is `null`. The agent uses this to decide whether to mention trend direction in its UI copy.

---

### 6.5 Agent Tool: `get_recommendations_for_case`

**Purpose:** Fetches targeted recommendations for a specific organ + user context combination. This is distinct from the general `get_recommendations` tool — it takes the user's stated goal (weight loss, energy, athletic performance, longevity) into account and shapes the output accordingly.

**Schema:**
```python
def get_recommendations_for_case(
    organ: str,
    use_case: str,              # e.g. "weight loss", "marathon prep", "general wellness"
    flagged_parameters: list[ParameterReading],
    severity: Literal["low", "medium", "high"]
) -> CaseRecommendations:
    """
    Returns goal-aware recommendations for this organ's flagged parameters.
    Calls Claude API internally with a use-case-aware prompt.
    """
```

**Output shape:**
```json
{
  "organ": "metabolic",
  "use_case": "weight loss",
  "diet": [
    { "title": "Reduce refined carbohydrates", "description": "Your HbA1c at 6.1% suggests early insulin resistance. Replacing white rice and bread with whole grains and legumes can reduce it by 0.3–0.5% over 3 months.", "priority": "high" }
  ],
  "exercise": [...],
  "supplements": [...],
  "products": [...],
  "quest_titles": ["30-day Low-GI Diet Challenge", "Daily 20-min Walk Quest"],
  "disclaimer": "These are general wellness suggestions, not medical advice. Consult a healthcare provider."
}
```

**Prompt strategy:** The Claude API call for this tool uses a two-part prompt: a static system prompt defining the health assistant persona and output schema, and a dynamic user prompt constructed from the organ data + use case. Results are cached by `(organ, use_case, frozenset(flagged_param_names))`.

---

### 6.6 Agent Tool: `build_organ_ui_section`

**Purpose:** This is the agent's UI-building tool. It uses FastMCP's **Generative UI** pattern — the agent writes Prefab Python code describing the UI section for one organ, which is executed in a Pyodide sandbox and returned as a rendered component block.

**Schema:**
```python
def build_organ_ui_section(
    organ: str,
    organ_data: OrganData,
    recommendations: CaseRecommendations,
    priority_rank: int,         # 1 = most critical, shown first
    show_trend: bool            # True if multi-report data exists
) -> PrefabUIBlock:
    """
    Agent writes Prefab Python to build the UI card for this organ.
    Executes in Pyodide sandbox. Returns a serialized component block
    that gets merged into the final PrefabApp.
    """
```

**What the agent generates (example output for Liver):**
```python
# Agent-generated Prefab code:
from prefab_ui.components import Column, Row, Card, CardContent, Heading, Text, Badge, Separator, Tabs, TabsList, TabsTrigger, TabsContent
from prefab_ui.components.charts import BarChart, ChartSeries, GaugeChart

with Column(gap=4) as section:
    with Card():
        with CardContent(css_class="p-5"):
            with Row(justify="between", align="center"):
                with Row(gap=2, align="center"):
                    Heading("🫀 Liver", level=3)
                    Badge("Score: 82/100", variant="success")
                Badge("Priority #2", variant="outline")

            Text("All liver markers are within normal range. SGOT has improved from last report — keep it up.", css_class="text-muted-foreground mt-2")

            Separator(css_class="my-4")

            BarChart(
                data=organ_data["parameters"],
                series=[ChartSeries(data_key="value", label="Your Value")],
                x_axis="name",
            )

            with Tabs(default="diet"):
                with TabsList():
                    TabsTrigger("diet",    label="Diet")
                    TabsTrigger("exercise", label="Exercise")
                    TabsTrigger("supplements", label="Supplements")
                with TabsContent("diet"):
                    for rec in recommendations["diet"]:
                        Text(f"• {rec['title']}: {rec['description']}")
                # ... other tabs
```

**Key design point:** The agent is not calling `generate_prefab_ui` from the `GenerativeUI` provider directly — that provider is for the outer MCP host model. Instead, `build_organ_ui_section` is a dedicated agent tool that wraps the same Pyodide execution mechanism internally, but scoped to organ-level section generation. This keeps the agent's UI-building contained and composable.

---

### 6.7 Agent System Prompt

The internal Claude agent receives this system prompt when `run_health_agent` is called:

```
You are HealthQuest's internal health analysis agent. Your job is to analyze 
a user's lab data and build a personalized, gamified health dashboard.

You have exactly 4 tools available. Use them in this order:

1. prioritize_organs — call once, at the start. Decide which organ systems 
   to investigate based on the user's context and overall flag severity.
   Focus on the top 3–4 organs maximum.

2. get_params_by_organ — call once per organ, in priority order.
   Get the exact values and dates you need to reason about.

3. get_recommendations_for_case — call once per organ that has flagged 
   parameters. Pass the user's stated goal. Skip organs with no flags 
   (just build a "healthy" UI card for them).

4. build_organ_ui_section — call once per organ after you have its data 
   and recommendations. Write clear, encouraging Prefab Python code.
   Your tone should be: specific, actionable, motivating — never alarming.
   Always end with a quest suggestion derived from the recommendations.

When you have built all organ sections, call the special tool:
finish_dashboard — pass all completed section blocks and the overall score.
This signals the loop to stop and assemble the final PrefabApp.

Rules:
- Never invent parameter values. Only use data returned by get_params_by_organ.
- Never use diagnostic language ("you have diabetes", "liver disease").
- Always include the disclaimer on any recommendation section.
- Maximum 4 organ sections per dashboard to keep the UI scannable.
- If a parameter is only slightly out of range (< 10% deviation), 
  treat it as "borderline" not "flagged" in your copy.
```

---

### 6.8 Agent Loop Implementation Pattern

```python
# Inside run_health_agent tool handler:

import anthropic
from anthropic import Anthropic

client = Anthropic()
agent_tools = [prioritize_organs, get_params_by_organ, 
               get_recommendations_for_case, build_organ_ui_section,
               finish_dashboard]

messages = [{"role": "user", "content": build_agent_prompt(lab_data, context)}]

ui_sections = []

while True:
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=AGENT_SYSTEM_PROMPT,
        tools=[tool_schema(t) for t in agent_tools],
        messages=messages,
    )

    # Append assistant response to history
    messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "end_turn":
        break

    # Process tool calls
    tool_results = []
    for block in response.content:
        if block.type == "tool_use":
            if block.name == "finish_dashboard":
                # Agent is done — break out
                final_sections = block.input["sections"]
                goto assemble_final_ui  # pseudocode
            
            result = dispatch_agent_tool(block.name, block.input)
            
            if block.name == "build_organ_ui_section":
                ui_sections.append(result)  # collect UI blocks
            
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": serialize(result)
            })

    messages.append({"role": "user", "content": tool_results})

# Assemble all UI sections into final PrefabApp
return assemble_final_dashboard(ui_sections, overall_score)
```

---

### 6.9 `finish_dashboard` Signal Tool

A lightweight tool the agent calls when it's done, signalling the outer loop to stop. Takes no meaningful action — it's a structured stop signal.

```python
def finish_dashboard(
    sections_complete: int,
    overall_summary: str    # 1-sentence summary for the dashboard header
) -> dict:
    """Signal that all organ sections are built and the dashboard is ready."""
    return {"status": "done", "sections": sections_complete, "summary": overall_summary}
```

---

### 6.10 Agent vs. Outer Model — Separation of Concerns

| Concern | Outer MCP Host Model | Internal Health Agent |
|---|---|---|
| **Who calls it** | User / operator | `run_health_agent` tool handler |
| **What it sees** | All registered `@mcp.tool` tools | Only the 5 agent tools |
| **UI authority** | Can call any display tool | Builds UI sections via `build_organ_ui_section` |
| **State access** | Through MCP resources | Direct Python session state |
| **Token budget** | Managed by host | Controlled by `max_tokens` in SDK call |
| **Loop control** | Host decides when to stop | `finish_dashboard` signal |

This separation means the outer model (Claude in the MCP client) never gets confused by the agent's internal tools, and the agent can't accidentally expose internals to the user.

---

## 7. Gamification System

### 7.1 Scoring Model

```
Parameter Score (0–100):
  - Value within range = 70 + (proximity to midpoint / half-range) × 30
  - Value outside range = max(0, 70 - (deviation / range_width) × 70)

Organ Score (0–100):
  - Weighted average of parameter scores within that organ
  - Critical parameters (e.g. creatinine, hemoglobin) weighted 2×

Overall Health Score (0–1000):
  - Weighted sum of organ scores × organ weights
  - Organ weights defined in organ_map.json (e.g. Heart = 0.20, Liver = 0.15)
```

### 7.2 Level & Rank System

| Score | Level | Rank | Badge Color |
|---|---|---|---|
| 0–399 | 1–4 | Bronze | 🟤 |
| 400–599 | 5–8 | Silver | ⚪ |
| 600–799 | 9–12 | Gold | 🟡 |
| 800–949 | 13–16 | Platinum | 🔵 |
| 950–1000 | 17–20 | Diamond | 💎 |

### 7.3 XP Events
- Upload a new report: +50 XP
- Complete a quest (parameter enters normal range): +quest XP reward
- Achieve new organ level: +100 XP bonus
- 3+ consecutive improving trends: +200 XP streak bonus

---

## 8. Organ-to-Parameter Mapping

| Organ System | Parameters (examples) |
|---|---|
| **Liver** | SGOT, SGPT, GGT, Alkaline Phosphatase, Bilirubin (Total/Direct/Indirect), Albumin, Total Protein, A/G Ratio |
| **Kidney** | Creatinine, BUN, eGFR, Uric Acid, Electrolytes (Na, K, Cl) |
| **Heart / Lipids** | Total Cholesterol, LDL, HDL, Triglycerides, VLDL, Hs-CRP |
| **Blood (CBC)** | Hemoglobin, Hematocrit, WBC, RBC, Platelets, MCV, MCH, MCHC |
| **Thyroid** | TSH, T3, T4, Free T3, Free T4 |
| **Metabolic** | Fasting Glucose, HbA1c, Insulin, HOMA-IR |
| **Vitamins & Minerals** | Vitamin D, Vitamin B12, Folate, Iron, Ferritin, Calcium, Magnesium |
| **Hormones** | Testosterone, Estradiol, Cortisol, DHEA-S, FSH, LH |

---

## 9. AI Recommendation Prompt Design

Each call to `get_recommendations` sends Claude a structured prompt:

```
You are a health optimization assistant. A user's lab report shows the following 
flagged parameters for their {organ} health:

{flagged_parameters_with_values_and_ranges}

Generate evidence-based, actionable recommendations in exactly this JSON format:
{
  "diet": [...],
  "exercise": [...],
  "supplements": [...],
  "products": [...]
}

Each item: { "title": str, "description": str (1-2 sentences), "priority": "high|medium|low" }
Max 3 items per category. Be specific and practical. 
Always include: "Note: These are general wellness suggestions, not medical advice."
```

---

## 10. Installation & Setup

```bash
# Install
pip install "fastmcp[apps]" pdfplumber anthropic pydantic

# Run locally (stdio transport — for Claude Desktop)
fastmcp run server.py

# Run as HTTP server (for remote clients)
fastmcp run server.py --transport streamable-http --port 8000

# Install into Claude Desktop
fastmcp install server.py --name "HealthQuest"
```

### Claude Desktop `mcp.json` entry
```json
{
  "mcpServers": {
    "healthquest": {
      "command": "python",
      "args": ["-m", "healthquest.server"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key-here"
      }
    }
  }
}
```

---

## 11. MVP Scope (Phase 1)

**In scope for initial build:**
- JSON ingestion only (PDF in Phase 2)
- Liver, Kidney, Blood, Metabolic organ panels
- `show_health_dashboard`, `show_organ_panel`, `show_gauge_chart`, `show_bar_comparison`
- `get_recommendations` (AI-powered)
- `run_health_agent` with all 5 agent tools (prioritize_organs, get_params_by_organ, get_recommendations_for_case, build_organ_ui_section, finish_dashboard)
- Agent loop with single-report analysis (no trend reasoning)
- `show_active_quests`
- Basic XP + Level scoring
- `stdio` transport only

**Deferred to Phase 2:**
- PDF parsing
- `show_trend_chart` + `compare_reports` (needs multi-report storage)
- All remaining organ systems
- `show_radar_chart`
- Product recommendation database
- Multi-report trend reasoning in agent (requires compare_reports)
- HTTP transport + hosted deployment

---

## 12. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Prefab UI breaking changes (early library) | Pin `prefab-ui` to a specific version; test before upgrading |
| MCP Apps not supported in user's client | Document supported clients; fall back to text output when `app=True` is unsupported |
| AI recommendation quality | Use structured JSON output with strict prompt; validate schema before rendering |
| PDF parsing inconsistency | Start with JSON-only MVP; add PDF as Phase 2 with manual fallback |
| Medical liability | Prominent disclaimer on every recommendation; never use diagnostic language |

---

## 13. Success Metrics

| Metric | Target |
|---|---|
| Tool invocation → UI render time | < 2 seconds |
| Parameter parsing accuracy (JSON) | 100% |
| Recommendation relevance (manual review) | > 85% rated "useful" |
| Quest completion (simulated, improving report) | Correctly awards XP |
| Supported organ systems at launch | 4 |
| Supported organ systems at v2 | 8+ |
