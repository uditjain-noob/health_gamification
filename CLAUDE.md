# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_scorer.py

# Run a single test by name
uv run pytest tests/test_scorer.py::test_score_parameter_midpoint_is_100

# Start the MCP dev server (hot-reload, opens MCP inspector)
fastmcp dev server.py

# Seed local SQLite with sample data (outputs patient_id)
python seed.py
```

Python version: 3.12 (see `fastmcp.json`). Dependencies managed with `uv`; `pyproject.toml` uses hatchling.

## Environment

Copy `.env.example` to `.env` and set at minimum:
- `GOOGLE_API_KEY` — required for LLM calls (Gemini 2.0 Flash by default)
- `DB_PATH` — local SQLite path (default: `healthquest.db`)
- `TURSO_URL` + `TURSO_AUTH_TOKEN` — optional, enables Turso cloud sync

## Architecture

**HealthQuest is a FastMCP server** that turns raw lab data into a gamified health dashboard rendered as Prefab UI components inside MCP-compatible AI clients (Claude, Goose, etc.).

### Tool registration pattern

Every feature lives in `apps/` or `agent/`. Each module exposes a `register(mcp, get_store, ...)` function that defines `@mcp.tool()` decorated handlers and closes over lazy dependency factories. `server.py` imports and calls all `register()` functions at startup, with singletons for `Store` and `GeminiClient` initialized lazily on first use (via `config.py`).

### Data pipeline

```
PDF/JSON → core/parser.py (Parser) → normalized list[dict]
         → core/organs.py (OrganMapper) → organ assigned per parameter
         → db/store.py (Store) → persisted in SQLite or Turso
```

`Parser.parse_json()` auto-detects two known JSON schemas ("sample" with `parameterValues`/`range`, "simple" with `readings`/`ref_min`/`ref_max`) and falls back to LLM normalization for unknown formats. `Parser.parse_pdf()` always uses LLM extraction via pdfplumber text dump.

`OrganMapper` loads `data/organ_map.json` at startup and maps parameter names to organ buckets (liver, kidney, heart, etc.) via exact-match then longest-substring fallback. It also tracks critical parameters (2× weight in scoring) and organ weights for the overall score.

### Scoring system

All scoring is pure functions in `core/scorer.py`:
- **Per-parameter (0–100):** 70–100 when in range (proximity to midpoint), 0–70 out of range (linear penalty by deviation over range width)
- **Per-organ (0–100):** weighted average of latest readings; critical parameters get 2× weight
- **Overall (0–1000):** organ scores × organ weights × 10, capped at 1000

Gamification outputs: Rank (Bronze → Diamond), Level (1–20 across 5 bands), XP (10/20/30 per Easy/Medium/Hard quest difficulty).

### Database

`Store` wraps either `sqlite3` (local) or `db/turso.py` (`TursoConnection`, a custom sqlite3-compatible HTTP client for Turso's pipeline API). Schema: `patients → reports → parameters → readings` (denormalized: `patient_id` on `parameters` for fast per-patient queries) + `xp_log`. Readings are append-only; parameters are upserted (ref range updated to latest, readings accumulated across reports).

### Autonomous agent (`agent/`)

`run_health_agent` in `apps/agent/runner.py` runs a full Gemini tool-use loop. The agent receives organ summaries and a user context, then autonomously calls: `prioritize_organs → get_params_by_organ → get_recommendations_for_case → build_organ_ui_section → finish_dashboard`. The loop in `llm/gemini.py` (`GeminiClient.tool_loop`) terminates when `finish_dashboard` is called (the configured `stop_tool`). UI component objects (Prefab) are serialized as `<ClassName>` placeholders when fed back to the model to avoid JSON serialization errors.

### RAG (`apps/rag_retriever.py`)

Optional Haystack `InMemoryDocumentStore` loaded from `scripts/excercise_diet_reco/corpus/store.json`. If the file is absent the module silently no-ops — the server runs without RAG grounding. Call `load_store()` once at startup to enable embedding-based retrieval for recommendations.

### UI rendering

All tools that return dashboards/panels use `prefab_ui` components (`Column`, `Card`, `Badge`, `Ring`, `BarChart`, etc.) composed inside context managers and returned as a `PrefabApp`. These render natively in MCP clients; they are not HTML.
