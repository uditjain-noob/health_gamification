# HealthQuest — Design Spec
**Date:** 2026-05-12  
**Status:** Approved for implementation  
**Phase:** 1 (MVP)

---

## 1. Overview

HealthQuest is a FastMCP server that turns raw lab report data into a gamified, interactive health dashboard. Users upload lab results (JSON or PDF), receive organ-level health scores, XP, quests, and AI-generated recommendations — all rendered as Prefab UI inside any MCP-compatible client. An internal Gemini-powered agent loop autonomously prioritizes organs, fetches data, generates recommendations, and assembles the final dashboard.

---

## 2. Phase 1 Scope

**In scope:**
- JSON ingestion (flexible normalizer + LLM fallback for unknown shapes)
- PDF ingestion via LLM extraction (pdfplumber text → Gemini → canonical JSON)
- 4 organ panels: Liver, Kidney, Blood (CBC), Metabolic
- Tools: `upload_report`, `show_health_dashboard`, `show_organ_panel`, `show_bar_comparison`, `show_gauge_chart`, `get_recommendations`, `show_active_quests`, `run_health_agent`
- Full agentic loop with 5 internal agent tools
- XP + Level + Rank scoring
- Multi-patient support via `patient_id`
- SQLite persistence
- Gemini as LLM provider (configurable via env vars)
- `stdio` transport; tested via `fastmcp dev server.py`

**Deferred to Phase 2:**
- `show_trend_chart`, `compare_reports`, `show_radar_chart`
- Remaining organ systems (Thyroid, Heart/Lipids, Vitamins, Hormones)
- Product recommendation database
- HTTP transport + hosted deployment
- Anthropic adapter

---

## 3. Directory Structure

```
healthquest/
├── server.py                  # FastMCP entry point
├── config.py                  # LLM provider, model, API keys from env
│
├── core/
│   ├── models.py              # Pydantic v2 models
│   ├── parser.py              # JSON normalizer + PDF extraction
│   ├── scorer.py              # Scoring engine (pure functions)
│   └── organs.py             # Organ-to-parameter mapping + fuzzy matcher
│
├── db/
│   └── store.py               # SQLite via stdlib sqlite3
│
├── llm/
│   └── gemini.py              # GeminiClient: complete() + tool_loop()
│
├── apps/
│   ├── ingest.py              # upload_report
│   ├── dashboard.py           # show_health_dashboard
│   ├── organ_panel.py         # show_organ_panel
│   ├── charts.py              # show_bar_comparison, show_gauge_chart
│   ├── recommendations.py     # get_recommendations
│   └── quests.py              # show_active_quests
│
├── agent/
│   ├── runner.py              # run_health_agent — outer @mcp.tool(app=True)
│   ├── loop.py                # Gemini tool-use loop
│   ├── tools.py               # 5 internal agent tools
│   ├── prompts.py             # System prompt variants (progressive / batch)
│   └── assembler.py          # Merges UIBlocks into final PrefabApp
│
└── data/
    ├── organ_map.json          # Parameter name → organ + critical weight flags
    ├── reference_ranges.json   # Fallback normal ranges
    └── products.json           # Placeholder for Phase 2
```

---

## 4. Data Models (`core/models.py`)

```python
class Patient(BaseModel):
    id: str                          # uuid
    name: str | None = None
    created_at: datetime

class ParameterReading(BaseModel):
    date: datetime
    value: float
    status: Literal["normal", "high", "low"]  # computed on ingest

class Parameter(BaseModel):
    name: str                        # normalized (e.g. "SGOT")
    raw_name: str                    # original from report
    unit: str
    organ: str                       # assigned by organs.py
    reference_min: float
    reference_max: float
    readings: list[ParameterReading]
    trend: Literal["improving", "declining", "stable", None]

class LabResult(BaseModel):
    id: str                          # uuid
    patient_id: str
    source_file: str
    ingested_at: datetime
    parameters: list[Parameter]

class OrganSummary(BaseModel):
    organ: str
    score: int                       # 0–100
    flagged_count: int
    parameter_count: int
    rank: Literal["Optimal", "Good", "At Risk", "Critical"]
```

---

## 5. SQLite Schema (`db/store.py`)

Four tables, created on first run:

```sql
CREATE TABLE patients (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    created_at  TEXT
);

CREATE TABLE reports (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    source_file TEXT,
    ingested_at TEXT
);

CREATE TABLE parameters (
    id          TEXT PRIMARY KEY,
    report_id   TEXT NOT NULL REFERENCES reports(id),
    patient_id  TEXT NOT NULL REFERENCES patients(id),  -- denormalized for fast queries
    name        TEXT NOT NULL,
    raw_name    TEXT,
    unit        TEXT,
    organ       TEXT,
    ref_min     REAL,
    ref_max     REAL
);

CREATE TABLE readings (
    id           TEXT PRIMARY KEY,
    parameter_id TEXT NOT NULL REFERENCES parameters(id),
    result_date  TEXT,
    value        REAL,
    status       TEXT
);

CREATE TABLE xp_log (
    id         TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    event      TEXT,
    xp_awarded INTEGER,
    created_at TEXT
);
```

**Key query patterns:**
- `get_all_parameters_for_organ(patient_id, organ)` — `WHERE patient_id = ? AND organ = ?` (no join needed, `patient_id` denormalized onto `parameters`)
- `get_latest_report(patient_id)` — `ORDER BY ingested_at DESC LIMIT 1`
- `get_xp_total(patient_id)` — `SUM(xp_awarded) WHERE patient_id = ?`

---

## 6. Parser (`core/parser.py`)

**JSON ingestion — two paths:**

1. **Auto-detect:** Tries to map known field name variants (`parameter`/`name`/`test`, `range`/`referenceRange`, `value`/`result`, `parameterValues`/`readings`). If all fields resolve confidently → normalize directly.
2. **LLM fallback:** If field detection fails → send raw JSON to `GeminiClient.complete()` asking it to return the canonical array shape. Used for unknown lab provider formats.

**PDF ingestion:**

1. Extract text via `pdfplumber`
2. Send text to `GeminiClient.complete()` with a prompt instructing it to return a JSON array in canonical shape
3. Validate output through Pydantic

**Canonical shape (internal):**
```json
[{
  "parameter": "SGOT",
  "unit": "U/L",
  "reference_min": 0.0,
  "reference_max": 31.0,
  "readings": [{"date": "2025-10-15", "value": 27.76}]
}]
```

**Organ assignment** (`core/organs.py`):
1. Exact match on normalized parameter name
2. Substring match (handles `"ASPARTATE AMINOTRANSFERASE (SGOT )"` → `"SGOT"`)
3. Unmatched → `"other"` bucket (stored, not surfaced in Phase 1 UI)

---

## 7. Scoring Engine (`core/scorer.py`)

Pure functions — no DB access, fully testable.

**Parameter score (0–100):**
```
within range:  score = 70 + (proximity_to_midpoint / half_range) × 30
outside range: score = max(0, 70 − (deviation_from_range / range_width) × 70)
```

**Organ score (0–100):**
- Weighted average of parameter scores
- Critical parameters (Creatinine, Hemoglobin, HbA1c, TSH, eGFR) weighted 2×
- Critical parameter list defined in `organ_map.json`

**Overall health score (0–1000):**
- Weighted sum of organ scores × organ weights from `organ_map.json`
- Default weights: Heart=0.20, Liver=0.15, Kidney=0.15, Blood=0.15, Metabolic=0.15, Thyroid=0.10, Vitamins=0.05, Hormones=0.05
- Only organs with at least one parameter in the report contribute

**Level & Rank:**
| Score   | Rank     | Levels |
|---------|----------|--------|
| 0–399   | Bronze   | 1–4    |
| 400–599 | Silver   | 5–8    |
| 600–799 | Gold     | 9–12   |
| 800–949 | Platinum | 13–16  |
| 950–1000| Diamond  | 17–20  |

**XP events** (written to `xp_log`):
- Upload report: +50 XP
- Parameter enters normal range vs previous report: +10 XP (Easy), +20 XP (Medium), +30 XP (Hard) — difficulty based on prior deviation
- New organ level achieved: +100 XP bonus

---

## 8. LLM Layer (`llm/gemini.py`)

Single implementation for Phase 1. Clean two-method interface so an Anthropic adapter can be added later with no changes to calling code.

```python
class GeminiClient:
    def complete(self, system: str, user: str) -> str:
        """Single-shot text/JSON completion."""

    def tool_loop(self, system: str, messages: list, tools: list) -> ToolLoopResult:
        """Runs Gemini function-calling loop until finish_dashboard is signalled."""
```

**Config (`config.py`):**
```
LLM_MODEL     = os.getenv("LLM_MODEL", "gemini-2.0-flash")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
```

`GeminiClient` is instantiated once at server startup and injected into all tools via FastMCP's dependency context.

---

## 9. FastMCP Tools

### `upload_report` (`apps/ingest.py`)
- **Type:** `@mcp.tool()` (text output)
- **Input:** `patient_id: str | None`, `file_path: str | None`, `data: list[dict] | None`, `patient_name: str | None`
- **Behaviour:** Creates patient if `patient_id` is None. Parses input, validates through Pydantic, assigns organs, writes to SQLite, awards +50 XP.
- **Returns:** Summary string including assigned `patient_id`, parameter count, organ breakdown, and any parse warnings.

### `show_health_dashboard` (`apps/dashboard.py`)
- **Type:** `@mcp.tool(app=True)`
- **Input:** `patient_id: str`
- **UI:** Header (rank badge, score/1000, XP Progress bar) → Grid(columns=3) of organ Cards → quick stats Row → top 3 quest Badges

### `show_organ_panel` (`apps/organ_panel.py`)
- **Type:** `@mcp.tool(app=True)`
- **Input:** `patient_id: str`, `organ: str`
- **UI:** Hero Card → DataTable (parameter/value/range/status/delta) → Ring components for out-of-range params → Tabs (Diet / Exercise / Supplements)

### `show_bar_comparison` (`apps/charts.py`)
- **Type:** `@mcp.tool(app=True)`
- **Input:** `patient_id: str`, `organ: str`
- **UI:** BarChart of all organ parameters sorted by deviation (worst first); Metric showing reference range alongside each bar

### `show_gauge_chart` (`apps/charts.py`)
- **Type:** `@mcp.tool(app=True)`
- **Input:** `patient_id: str`, `parameter: str`
- **UI:** Large Ring component + Metric (value + unit) + status Badge + Sparkline if multiple readings exist

### `get_recommendations` (`apps/recommendations.py`)
- **Type:** `@mcp.tool()` (text output)
- **Input:** `patient_id: str`, `organ: str`
- **Behaviour:** Fetches flagged parameters from SQLite, calls `GeminiClient.complete()` with structured prompt, returns `{ diet, exercise, supplements }`. Cached in-memory by `(patient_id, organ)`.

### `show_active_quests` (`apps/quests.py`)
- **Type:** `@mcp.tool(app=True)`
- **Input:** `patient_id: str`
- **UI:** One Card per out-of-range parameter — quest name, organ badge, difficulty badge (Easy <20% / Medium 20–50% / Hard >50% deviation), XP reward, action description. Progress bar showing quests resolved vs total.

### `run_health_agent` (`agent/runner.py`)
- **Type:** `@mcp.tool(app=True)`
- **Input:** `patient_id: str`, `context: str = ""`, `style: Literal["progressive", "batch"] = "progressive"`, `report_ids: list[str] | None = None`
- **Returns:** Fully assembled `PrefabApp` dashboard built by the internal agent

---

## 10. Agent Loop (`agent/`)

### Entry point (`agent/runner.py`)
1. Load organ summaries from SQLite for patient
2. Build system + user prompts via `agent/prompts.py`
3. Run `agent/loop.py` → collect `UIBlock` list
4. Pass blocks to `agent/assembler.py` → final `PrefabApp`

### Tool-use loop (`agent/loop.py`)
Runs `GeminiClient.tool_loop()` in a while loop. Collects `build_organ_ui_section` outputs in arrival order. Exits on `finish_dashboard` signal.

### Internal agent tools (`agent/tools.py`)
Not exposed as MCP tools — registered only with the Gemini agent:

| Tool | Purpose |
|------|---------|
| `prioritize_organs` | Returns ordered organ list with reasoning based on scores + user context |
| `get_params_by_organ` | Fetches all readings + ranges from SQLite for one organ |
| `get_recommendations_for_case` | Goal-aware recommendation call to Gemini; cached by `(organ, use_case, flagged_params)` |
| `build_organ_ui_section` | Builds Prefab component tree for one organ (Card + DataTable + Ring/Sparkline + Tabs); returns serialized UIBlock |
| `finish_dashboard` | Stop signal — exits loop, passes blocks to assembler |

### System prompt variants (`agent/prompts.py`)

**`progressive` (default):** Agent builds UI section immediately after fetching data + recommendations for each organ, before moving to the next.

**`batch`:** Agent fetches all organ data and recommendations first, then builds all UI sections at the end.

Both variants share core rules: max 4 organs per dashboard, never invent parameter values, never use diagnostic language, always append disclaimer on recommendations.

### Assembler (`agent/assembler.py`)
Order-agnostic — takes UIBlocks in arrival order and wraps them in a top-level `PrefabApp` with a header (rank badge, overall score, XP bar) and footer (disclaimer + "View All Quests" Button).

---

## 11. Prefab UI Component Mapping

| PRD component | Actual prefab-ui component |
|---------------|---------------------------|
| `GaugeChart` | `Ring` |
| `LineChart` / trend | `Sparkline` |
| `ProgressBar` | `Progress` |
| `BarChart` | `BarChart` ✓ |
| `RadarChart` | `RadarChart` ✓ (Phase 2) |
| `DataTable` | `DataTable` ✓ |
| `Badge` | `Badge` ✓ |
| `Tabs` | `Tabs` ✓ |
| `Grid` | `Grid` ✓ |
| `Card` | `Card` ✓ |

---

## 12. Testing Strategy

**Layer 1 — Unit tests (no MCP, no network):**
- `scorer.py` — known inputs → assert scores and ranks
- `parser.py` — sample JSON shapes → assert normalized Pydantic output
- `organs.py` — messy real lab names → assert correct organ assignment
- `db/store.py` — in-memory SQLite (`:memory:`) → assert all query patterns

**Layer 2 — Tool integration tests:**
- Call tool functions directly as Python (bypass MCP protocol)
- Mock `GeminiClient` for recommendation and agent loop tests
- Assert correct Pydantic models, SQLite writes, XP events, and `PrefabApp` structure

**Layer 3 — Manual via FastMCP dev server:**
- `fastmcp dev server.py` in browser
- Upload `sample_organ_data.json`, exercise all tools visually
- Verify dashboard renders, organ panels load, quests display correctly

---

## 13. Installation

```bash
pip install "fastmcp[apps]" prefab-ui pdfplumber google-genai pydantic

# Dev server
fastmcp dev server.py

# stdio (Claude Desktop)
fastmcp run server.py
```

**Environment variables:**
```
GOOGLE_API_KEY=your-key
LLM_MODEL=gemini-2.0-flash      # optional, this is the default
```

---

## 14. Open Questions / Phase 2 Notes

- Anthropic adapter: add `llm/anthropic.py` conforming to same two-method interface; add `LLM_PROVIDER` env var to switch
- `show_trend_chart` + `compare_reports`: need multi-report queries; SQLite schema already supports this
- Remaining organ systems: extend `organ_map.json` + add organ panels
- PDF parsing quality: validate against 3–5 real lab PDFs before Phase 2 ship
- `products.json`: populate with curated supplement data in Phase 2
