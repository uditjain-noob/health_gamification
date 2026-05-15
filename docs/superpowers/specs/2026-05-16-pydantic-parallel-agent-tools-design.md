# Design: Pydantic Inputs, Parallel Tool Execution, Agent Tools as MCP Tools

**Date:** 2026-05-16  
**Status:** Approved

---

## Overview

Three coordinated changes to the agent and MCP layer:

1. **Pydantic input models** on all `@mcp.tool()` functions and all `AgentTool` instances, replacing hand-written type annotations and JSON Schema dicts.
2. **Agent tools exposed as MCP tools** so they can be called directly by any MCP client, not only by the internal agent loop.
3. **Parallel tool execution** in the agent loop using `ThreadPoolExecutor`, so multiple tools called in the same Gemini turn execute concurrently.

---

## Motivation

- `get_recommendations_for_case` makes a live Gemini HTTP call (~1–3s). When the agent calls recommendations for 3–4 organs in one turn, sequential execution serialises those calls. Parallel execution makes wall-clock time equal to the slowest single call.
- RAG embedding (`_text_embedder.run()`) is similarly slow. Same benefit applies.
- Pydantic gives FastMCP richer auto-generated JSON schemas for free, and replaces ~80 lines of hand-written `"type": "object"` dicts in `agent/tools.py`.
- Exposing agent tools as MCP tools lets external callers (other agents, MCP clients) invoke `get_params_by_organ`, `get_recommendations_for_case`, etc. directly without going through `run_health_agent`.

---

## Architecture

### New file: `agent/mcp_tools.py`

Holds standalone functions (not closures) for the five agent operations, each with a Pydantic input model:

| Tool | Input Model | Slow I/O? |
|---|---|---|
| `prioritize_organs` | `PrioritizeOrgansInput` | No |
| `get_params_by_organ` | `GetParamsByOrganInput` | No (DB read) |
| `get_recommendations_for_case` | `GetRecommendationsInput` | Yes — Gemini call |
| `build_organ_ui_section` | `BuildOrganUISectionInput` | No |
| `finish_dashboard` | `FinishDashboardInput` | No |

Because these are no longer closures, `patient_id` becomes an explicit parameter on every function that needs it (`get_params_by_organ`, `get_recommendations_for_case`, `build_organ_ui_section`).

`register(mcp, get_store, get_mapper, get_client)` in this file registers all five as `@mcp.tool()`.

### Updated `agent/tools.py` — `make_agent_tools()`

`make_agent_tools()` still exists for backward compatibility with `agent/runner.py`. It now builds `AgentTool` wrappers by binding `patient_id` into thin lambdas over the standalone functions from `agent/mcp_tools.py`.

**Schema split:** each tool that needs `patient_id` has two Pydantic models:
- **`<Tool>Input`** — full model used for MCP tool registration (includes `patient_id`)
- **`<Tool>AgentInput`** — agent-facing model without `patient_id`, used for `AgentTool.parameters` so Gemini is not asked to supply a field it doesn't know

```python
class GetParamsByOrganInput(BaseModel):      # MCP tool — full
    patient_id: str
    organ: str

class GetParamsByOrganAgentInput(BaseModel): # AgentTool — no patient_id
    organ: str

AgentTool(
    name="get_params_by_organ",
    description="...",
    parameters=GetParamsByOrganAgentInput.model_json_schema(),
    fn=lambda organ: get_params_by_organ_fn(patient_id=patient_id, organ=organ, store=store, mapper=mapper)
)
```

Tools with no `patient_id` (`prioritize_organs`, `finish_dashboard`) use the same model for both MCP and agent registration.

### Pydantic on existing `apps/` MCP tools

Each `@mcp.tool()` function in `apps/` gets a Pydantic `BaseModel` input class. FastMCP v3 accepts a model instance as the sole parameter and unpacks it automatically.

Files to update: `apps/ingest.py`, `apps/dashboard.py`, `apps/organ_panel.py`, `apps/charts.py`, `apps/recommendations.py`, `apps/quests.py`, `apps/inspector.py`, `apps/query.py`.

Example:
```python
class UploadReportInput(BaseModel):
    patient_id: str | None = None
    patient_name: str | None = None
    file_path: str | None = None
    data: list[dict] | None = None

@mcp.tool()
def upload_report(input: UploadReportInput) -> str:
    ...
```

### Parallel execution in `llm/gemini.py`

Replace the sequential `for part in fn_calls` loop with `ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _dispatch(part, tool_map):
    fc = part.function_call
    tool = tool_map.get(fc.name)
    args = dict(fc.args)
    output = tool.fn(**args) if tool else {"error": f"Unknown tool: {fc.name}"}
    return ToolCall(name=fc.name, input=args, output=output)

with ThreadPoolExecutor() as pool:
    futures = {pool.submit(_dispatch, part, tool_map): part for part in fn_calls}
    call_results = [f.result() for f in as_completed(futures)]
```

**Stop-tool handling:** after all futures complete, check if any result's `name == self._stop_tool`. If yes, return immediately with accumulated results. This means `finish_dashboard` can be called in the same batch as other tools — the batch completes first, then the loop exits.

**Thread safety:**
- `sqlite3(check_same_thread=False)` — already set in `Store`
- `httpx.Client` (Turso) — thread-safe
- `genai.Client` (Gemini) — thread-safe (stateless HTTP)
- RAG `_text_embedder` (sentence-transformers) — model inference is thread-safe in read-only mode; the module-level singleton is only written at `load_store()` startup

**Error handling:** each `_dispatch` call wraps the tool function in try/except and returns `{"error": str(e)}` on failure — same behaviour as today, just per-thread.

---

## Data Flow (updated)

```
Gemini turn N
  └─ returns [fn_call_A, fn_call_B, fn_call_C]
        │
        ├── thread 1: get_params_by_organ("liver")     → DB read
        ├── thread 2: get_params_by_organ("kidney")    → DB read
        └── thread 3: get_recommendations_for_case(…)  → Gemini HTTP

  all complete → function_responses sent back in one user turn

Gemini turn N+1  (one fewer turn than before)
```

---

## What Does NOT Change

- `agent/runner.py` — `run_health_agent` is unchanged; it still calls `make_agent_tools()` and `run_agent_loop()`
- `agent/loop.py` — unchanged
- `agent/assembler.py` — unchanged
- `agent/prompts.py` — unchanged
- `db/store.py`, `core/`, `llm/` (except the parallel loop in `gemini.py`) — unchanged
- The external tool names and behaviours seen by Gemini — identical

---

## Testing

- Existing tests in `tests/` continue to pass (no core logic changes)
- New: `tests/test_agent_mcp_tools.py` — unit tests for each standalone tool function using a seeded in-memory Store
- Parallel execution: test that two slow mocked tools called in the same turn complete faster than their sequential sum (use `time.sleep` mocks)

---

## Files Changed

| File | Change |
|---|---|
| `agent/mcp_tools.py` | **New** — standalone tool functions + Pydantic models + MCP registration |
| `agent/tools.py` | Updated — `make_agent_tools()` wraps `agent/mcp_tools.py` functions |
| `llm/gemini.py` | Updated — `ThreadPoolExecutor` in `tool_loop()` |
| `apps/ingest.py` | Updated — Pydantic input model |
| `apps/dashboard.py` | Updated — Pydantic input model |
| `apps/organ_panel.py` | Updated — Pydantic input model |
| `apps/charts.py` | Updated — Pydantic input model |
| `apps/recommendations.py` | Updated — Pydantic input model |
| `apps/quests.py` | Updated — Pydantic input model |
| `apps/inspector.py` | Updated — Pydantic input model |
| `apps/query.py` | Updated — Pydantic input model |
| `server.py` | Updated — register `agent/mcp_tools.py` |
| `tests/test_agent_mcp_tools.py` | **New** — unit tests for standalone tool functions |
