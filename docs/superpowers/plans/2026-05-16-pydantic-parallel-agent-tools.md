# Pydantic Inputs, Parallel Tool Execution, Agent Tools as MCP Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Pydantic input models to all MCP and agent tools, expose agent tools as MCP tools, and execute agent tool calls in parallel using ThreadPoolExecutor.

**Architecture:** Extract a testable `_execute_tool_calls()` function from `GeminiClient.tool_loop()` that runs all tool calls in a single Gemini turn concurrently. Move agent tool logic into standalone functions in a new `agent/mcp_tools.py`, registered as both `@mcp.tool()` and wrapped as `AgentTool` instances in `agent/tools.py`. Add Pydantic `BaseModel` input classes to all `apps/` tools.

**Tech Stack:** Python 3.12, Pydantic v2, FastMCP v3, `concurrent.futures.ThreadPoolExecutor`, `google-genai`

---

## File Map

| File | Change |
|---|---|
| `llm/gemini.py` | Extract `_execute_tool_calls()` + use `ThreadPoolExecutor` |
| `agent/mcp_tools.py` | **New** — Pydantic models, standalone functions, MCP `register()` |
| `agent/tools.py` | `make_agent_tools()` wraps functions from `agent/mcp_tools.py` |
| `server.py` | Register `agent/mcp_tools` |
| `apps/ingest.py` | Pydantic `UploadReportInput` |
| `apps/dashboard.py` | Pydantic `ShowHealthDashboardInput` |
| `apps/query.py` | Pydantic models for 3 tools |
| `apps/organ_panel.py` | Pydantic `ShowOrganPanelInput` |
| `apps/charts.py` | Pydantic models for 3 tools |
| `apps/quests.py` | Pydantic `ShowActiveQuestsInput` |
| `apps/recommendations.py` | Pydantic `GetRecommendationsInput` |
| `apps/inspector.py` | Pydantic `ShowInspectorInput` |
| `tests/test_gemini_parallel.py` | **New** — parallel dispatch tests |
| `tests/test_agent_mcp_tools.py` | **New** — standalone agent tool function tests |

---

## Task 1: Parallel tool dispatch in `llm/gemini.py`

**Files:**
- Modify: `llm/gemini.py`
- Create: `tests/test_gemini_parallel.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gemini_parallel.py`:

```python
import time
from unittest.mock import MagicMock
from llm.gemini import _execute_tool_calls, AgentTool, ToolCall


def _make_part(name: str, args: dict):
    part = MagicMock()
    part.function_call.name = name
    part.function_call.args = args
    return part


def test_parallel_execution_faster_than_sequential():
    SLEEP = 0.15

    def slow_a(x):
        time.sleep(SLEEP)
        return {"a": x}

    def slow_b(x):
        time.sleep(SLEEP)
        return {"b": x}

    tool_map = {
        "tool_a": AgentTool(name="tool_a", description="", parameters={}, fn=slow_a),
        "tool_b": AgentTool(name="tool_b", description="", parameters={}, fn=slow_b),
    }
    parts = [_make_part("tool_a", {"x": 1}), _make_part("tool_b", {"x": 2})]

    start = time.monotonic()
    results = _execute_tool_calls(parts, tool_map)
    elapsed = time.monotonic() - start

    assert len(results) == 2
    # Parallel: should finish in ~SLEEP, not 2*SLEEP
    assert elapsed < SLEEP * 1.8
    result_names = {r.name for r in results}
    assert result_names == {"tool_a", "tool_b"}


def test_tool_error_does_not_kill_other_tools():
    def failing_tool(x):
        raise ValueError("oops")

    def good_tool(x):
        return {"value": x}

    tool_map = {
        "failing": AgentTool(name="failing", description="", parameters={}, fn=failing_tool),
        "good": AgentTool(name="good", description="", parameters={}, fn=good_tool),
    }
    parts = [_make_part("failing", {"x": 1}), _make_part("good", {"x": 42})]
    results = _execute_tool_calls(parts, tool_map)

    assert len(results) == 2
    failing = next(r for r in results if r.name == "failing")
    good = next(r for r in results if r.name == "good")
    assert "error" in failing.output
    assert good.output == {"value": 42}


def test_unknown_tool_returns_error_dict():
    parts = [_make_part("nonexistent", {"x": 1})]
    results = _execute_tool_calls(parts, tool_map={})

    assert len(results) == 1
    assert results[0].output == {"error": "Unknown tool: nonexistent"}


def test_single_tool_call_works():
    tool_map = {
        "echo": AgentTool(name="echo", description="", parameters={}, fn=lambda msg: {"echo": msg}),
    }
    results = _execute_tool_calls([_make_part("echo", {"msg": "hi"})], tool_map)
    assert results[0].output == {"echo": "hi"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_gemini_parallel.py -v
```

Expected: `ImportError: cannot import name '_execute_tool_calls'`

- [ ] **Step 3: Add `_execute_tool_calls` to `llm/gemini.py` and update `tool_loop`**

At the top of `llm/gemini.py`, add the import:
```python
from concurrent.futures import ThreadPoolExecutor
```

After the `_to_json_safe` function (around line 47), add the new function:
```python
def _execute_tool_calls(fn_calls: list, tool_map: dict) -> list["ToolCall"]:
    """Execute all fn_calls in parallel. Returns ToolCall results in completion order."""
    def dispatch(part) -> "ToolCall":
        fc = part.function_call
        tool = tool_map.get(fc.name)
        args = dict(fc.args)
        if tool is None:
            output = {"error": f"Unknown tool: {fc.name}"}
        else:
            try:
                output = tool.fn(**args)
            except Exception as e:
                output = {"error": str(e)}
                log.error("[agent] tool %s raised: %s", fc.name, e)
        log.info("[agent] ← tool_result: %s → %s", fc.name, json.dumps(_to_json_safe(output))[:200])
        return ToolCall(name=fc.name, input=args, output=output)

    with ThreadPoolExecutor() as pool:
        return list(pool.map(dispatch, fn_calls))
```

Then in `GeminiClient.tool_loop`, replace the sequential dispatch block. The old block (lines 127–160):
```python
            function_responses = []
            for part in fn_calls:
                fc = part.function_call
                tool = tool_map.get(fc.name)
                args = dict(fc.args)
                log.info("[agent] → tool_call: %s(%s)", fc.name, ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items()))

                if tool is None:
                    output = {"error": f"Unknown tool: {fc.name}"}
                else:
                    try:
                        output = tool.fn(**args)
                    except Exception as e:
                        output = {"error": str(e)}
                        log.error("[agent] tool %s raised: %s", fc.name, e)

                safe_output = _to_json_safe(output)
                log.info("[agent] ← tool_result: %s → %s", fc.name, json.dumps(safe_output)[:200])

                call = ToolCall(name=fc.name, input=args, output=output)
                results.append(call)

                if fc.name == self._stop_tool:
                    log.info("[agent] stop tool called — loop complete after %d turns", turn)
                    return results

                function_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": json.dumps(safe_output)},
                        )
                    )
                )
```

Replace with:
```python
            for part in fn_calls:
                fc = part.function_call
                log.info("[agent] → tool_call: %s(%s)", fc.name,
                         ", ".join(f"{k}={repr(v)[:60]}" for k, v in dict(fc.args).items()))

            call_results = _execute_tool_calls(fn_calls, tool_map)
            results.extend(call_results)

            # Check if stop tool was called in this batch
            stop_result = next((c for c in call_results if c.name == self._stop_tool), None)
            if stop_result:
                log.info("[agent] stop tool called — loop complete after %d turns", turn)
                return results

            function_responses = [
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name,
                        response={"result": json.dumps(_to_json_safe(call.output))},
                    )
                )
                for call in call_results
            ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_gemini_parallel.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
uv run pytest -v
```

Expected: all existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add llm/gemini.py tests/test_gemini_parallel.py
git commit -m "feat: parallel tool dispatch in agent loop via ThreadPoolExecutor"
```

---

## Task 2: Write tests for `agent/mcp_tools.py` standalone functions

**Files:**
- Create: `tests/test_agent_mcp_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_mcp_tools.py`:

```python
import pytest
from db.store import Store
from core.organs import OrganMapper
from agent.mcp_tools import (
    GetParamsByOrganInput,
    get_params_by_organ_fn,
    PrioritizeOrgansInput,
    prioritize_organs_fn,
    FinishDashboardInput,
    finish_dashboard_fn,
    GetRecommendationsForCaseInput,
)


@pytest.fixture
def store():
    s = Store(db_path=":memory:")
    s.initialize()
    return s


@pytest.fixture
def patient_id(store):
    pid = store.create_patient(name="Test Patient")
    store.save_report(
        patient_id=pid,
        source_file="test.json",
        parameters=[
            {
                "name": "SGOT",
                "raw_name": "SGOT",
                "unit": "U/L",
                "organ": "liver",
                "ref_min": 0.0,
                "ref_max": 31.0,
                "readings": [{"date": "2025-01-01", "value": 15.5, "status": "normal"}],
            },
            {
                "name": "SGPT",
                "raw_name": "SGPT",
                "unit": "U/L",
                "organ": "liver",
                "ref_min": 0.0,
                "ref_max": 34.0,
                "readings": [{"date": "2025-01-01", "value": 45.0, "status": "high"}],
            },
        ],
    )
    return pid


@pytest.fixture
def mapper():
    return OrganMapper()


# --- get_params_by_organ ---

def test_get_params_by_organ_returns_organ_and_params(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="liver"),
        store, mapper,
    )
    assert result["organ"] == "liver"
    assert len(result["parameters"]) == 2


def test_get_params_by_organ_counts_flagged(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="liver"),
        store, mapper,
    )
    assert result["flagged_count"] == 1  # SGPT is high


def test_get_params_by_organ_returns_score(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="liver"),
        store, mapper,
    )
    assert 0 <= result["organ_score"] <= 100


def test_get_params_by_organ_unknown_organ_returns_empty(store, patient_id, mapper):
    result = get_params_by_organ_fn(
        GetParamsByOrganInput(patient_id=patient_id, organ="pancreas"),
        store, mapper,
    )
    assert result["parameters"] == []
    assert result["flagged_count"] == 0


# --- prioritize_organs ---

def test_prioritize_organs_sorts_by_flagged_count():
    summaries = [
        {"organ": "liver", "flagged_count": 2, "score": 60},
        {"organ": "kidney", "flagged_count": 5, "score": 40},
        {"organ": "heart", "flagged_count": 0, "score": 90},
    ]
    result = prioritize_organs_fn(
        PrioritizeOrgansInput(context="", organ_summaries=summaries)
    )
    assert result[0]["organ"] == "kidney"
    assert result[1]["organ"] == "liver"


def test_prioritize_organs_limits_to_four():
    summaries = [
        {"organ": f"organ_{i}", "flagged_count": i, "score": 80 - i}
        for i in range(6)
    ]
    result = prioritize_organs_fn(
        PrioritizeOrgansInput(context="weight loss", organ_summaries=summaries)
    )
    assert len(result) <= 4


def test_prioritize_organs_includes_priority_rank():
    summaries = [{"organ": "liver", "flagged_count": 1, "score": 70}]
    result = prioritize_organs_fn(
        PrioritizeOrgansInput(context="", organ_summaries=summaries)
    )
    assert result[0]["priority"] == 1


# --- finish_dashboard ---

def test_finish_dashboard_returns_done_status():
    result = finish_dashboard_fn(
        FinishDashboardInput(sections_complete=3, overall_summary="Good health")
    )
    assert result["status"] == "done"


def test_finish_dashboard_preserves_section_count():
    result = finish_dashboard_fn(
        FinishDashboardInput(sections_complete=5, overall_summary="")
    )
    assert result["sections"] == 5


def test_finish_dashboard_preserves_summary():
    result = finish_dashboard_fn(
        FinishDashboardInput(sections_complete=1, overall_summary="Focus on liver")
    )
    assert result["summary"] == "Focus on liver"


# --- get_recommendations_for_case (mocked client) ---

def test_get_recommendations_returns_empty_when_no_flagged_params(store, patient_id):
    from agent.mcp_tools import get_recommendations_for_case_fn, GetRecommendationsForCaseInput
    from unittest.mock import MagicMock

    client = MagicMock()  # should not be called — no flagged params in list
    result = get_recommendations_for_case_fn(
        GetRecommendationsForCaseInput(
            patient_id=patient_id,
            organ="liver",
            use_case="weight loss",
            flagged_parameter_names=[],  # empty → no LLM call
            severity="low",
        ),
        store,
        client,
    )
    assert result["diet"] == []
    assert result["exercise"] == []
    client.complete.assert_not_called()


def test_get_recommendations_calls_llm_for_flagged_params(store, patient_id):
    from agent.mcp_tools import get_recommendations_for_case_fn, GetRecommendationsForCaseInput, _CASE_REC_CACHE
    from unittest.mock import MagicMock
    import json

    _CASE_REC_CACHE.clear()  # ensure no cached result
    mock_response = json.dumps({
        "diet": [{"title": "Eat less fat", "description": "Reduce saturated fat", "priority": "high"}],
        "exercise": [],
        "supplements": [],
        "quest_titles": [],
        "disclaimer": "Not medical advice.",
    })
    client = MagicMock()
    client.complete.return_value = mock_response

    result = get_recommendations_for_case_fn(
        GetRecommendationsForCaseInput(
            patient_id=patient_id,
            organ="liver",
            use_case="weight loss",
            flagged_parameter_names=["SGPT"],
            severity="medium",
        ),
        store,
        client,
    )

    client.complete.assert_called_once()
    assert result["diet"][0]["title"] == "Eat less fat"
    assert result["disclaimer"] == "Not medical advice."


# --- Pydantic validation ---

def test_get_params_by_organ_input_requires_patient_id():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GetParamsByOrganInput(organ="liver")  # missing patient_id


def test_get_recommendations_input_validates_severity():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GetRecommendationsForCaseInput(
            patient_id="abc",
            organ="liver",
            use_case="weight loss",
            flagged_parameter_names=["SGPT"],
            severity="invalid_value",
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_agent_mcp_tools.py -v
```

Expected: `ImportError: cannot import name 'GetParamsByOrganInput' from 'agent.mcp_tools'`

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_agent_mcp_tools.py
git commit -m "test: failing tests for agent/mcp_tools standalone functions"
```

---

## Task 3: Create `agent/mcp_tools.py`

**Files:**
- Create: `agent/mcp_tools.py`

- [ ] **Step 1: Create `agent/mcp_tools.py`**

```python
from __future__ import annotations

import json
import logging
from typing import Literal, Any

from pydantic import BaseModel, Field

from core.scorer import score_organ
from core.organs import OrganMapper
from db.store import Store

log = logging.getLogger("healthquest.agent.mcp_tools")

_CASE_REC_CACHE: dict[tuple, dict] = {}

_CASE_REC_PROMPT = """You are a health optimization assistant focused on: {use_case}

The patient's {organ} has these flagged markers:
{flagged}

Severity: {severity}

Return ONLY valid JSON:
{{
  "diet": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "exercise": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "supplements": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "quest_titles": [str],
  "disclaimer": "These are general wellness suggestions, not medical advice."
}}
Max 3 items per category. Tailor advice to the user's goal."""


# ── Pydantic input models (MCP — include patient_id) ─────────────────────────

class GetParamsByOrganInput(BaseModel):
    patient_id: str = Field(description="Patient UUID from upload_report")
    organ: str = Field(description="Organ name, e.g. 'liver', 'heart'")


class GetRecommendationsForCaseInput(BaseModel):
    patient_id: str = Field(description="Patient UUID from upload_report")
    organ: str = Field(description="Organ name")
    use_case: str = Field(description="User goal, e.g. 'weight loss', 'general wellness'")
    flagged_parameter_names: list[str] = Field(description="Names of out-of-range parameters")
    severity: Literal["low", "medium", "high"] = Field(description="Overall severity of flags")


class BuildOrganUISectionInput(BaseModel):
    organ: str = Field(description="Organ name")
    organ_score: int = Field(description="Organ score 0–100")
    parameters: list[dict] = Field(description="Parameter list from get_params_by_organ")
    recommendations: dict = Field(description="Recommendations dict from get_recommendations_for_case")
    priority_rank: int = Field(description="Organ priority rank (1 = highest)")


class PrioritizeOrgansInput(BaseModel):
    context: str = Field(default="", description="User goal or focus area")
    organ_summaries: list[dict] = Field(
        description="List of organ summaries with organ, score, flagged_count"
    )


class FinishDashboardInput(BaseModel):
    sections_complete: int = Field(description="Number of organ sections built")
    overall_summary: str = Field(description="1-2 sentence overall health summary")


# ── Agent-facing models (no patient_id — agent has it from context) ───────────

class GetParamsByOrganAgentInput(BaseModel):
    organ: str = Field(description="Organ name, e.g. 'liver', 'heart'")


class GetRecommendationsForCaseAgentInput(BaseModel):
    organ: str = Field(description="Organ name")
    use_case: str = Field(description="User goal, e.g. 'weight loss', 'general wellness'")
    flagged_parameter_names: list[str] = Field(description="Names of out-of-range parameters")
    severity: Literal["low", "medium", "high"] = Field(description="Overall severity of flags")


# ── Standalone functions ──────────────────────────────────────────────────────

def get_params_by_organ_fn(
    input: GetParamsByOrganInput,
    store: Store,
    mapper: OrganMapper,
) -> dict:
    params = store.get_parameters_for_organ(input.patient_id, input.organ)
    critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
    organ_score = score_organ(params, critical)
    flagged_count = sum(
        1 for p in params if p["readings"] and p["readings"][0]["status"] != "normal"
    )
    return {
        "organ": input.organ,
        "parameters": params,
        "organ_score": organ_score,
        "flagged_count": flagged_count,
    }


def get_recommendations_for_case_fn(
    input: GetRecommendationsForCaseInput,
    store: Store,
    client: Any,
) -> dict:
    cache_key = (input.patient_id, input.organ, tuple(sorted(input.flagged_parameter_names)))
    if cache_key in _CASE_REC_CACHE:
        return _CASE_REC_CACHE[cache_key]

    params = store.get_parameters_for_organ(input.patient_id, input.organ)
    flagged = [p for p in params if p["name"] in input.flagged_parameter_names]
    if not flagged:
        return {"diet": [], "exercise": [], "supplements": [], "quest_titles": [], "disclaimer": ""}

    flagged_text = "\n".join(
        f"- {p['name']}: {p['readings'][0]['value']} {p['unit']} "
        f"(normal: {p['ref_min']}–{p['ref_max']})"
        for p in flagged if p.get("readings")
    )
    try:
        raw = client.complete(
            system="You are a health optimization assistant. Return ONLY valid JSON.",
            user=_CASE_REC_PROMPT.format(
                use_case=input.use_case or "general wellness",
                organ=input.organ,
                flagged=flagged_text,
                severity=input.severity,
            ),
        )
        result = json.loads(raw)
    except Exception:
        result = {"diet": [], "exercise": [], "supplements": [], "quest_titles": [], "disclaimer": ""}

    _CASE_REC_CACHE[cache_key] = result
    return result


def build_organ_ui_section_fn(
    input: BuildOrganUISectionInput,
    mapper: OrganMapper,
) -> dict:
    from prefab_ui.components import (
        Column, Row, Card, CardContent, Heading, Text, Badge, Separator, Muted,
    )
    from prefab_ui.components import Ring
    from prefab_ui.components.charts import BarChart, ChartSeries

    rank = (
        "Optimal" if input.organ_score >= 90
        else "Good" if input.organ_score >= 70
        else "At Risk" if input.organ_score >= 50
        else "Critical"
    )
    rank_variant = {"Optimal": "success", "Good": "default", "At Risk": "warning", "Critical": "destructive"}
    emoji = mapper.get_organ_emoji(input.organ)
    flagged = [
        p for p in input.parameters
        if p.get("readings") and p["readings"][0]["status"] != "normal"
    ]

    chart_data = [
        {"name": p["name"], "value": p["readings"][0]["value"]}
        for p in input.parameters if p.get("readings")
    ]

    with Column(gap=4) as section:
        with Card():
            with CardContent(css_class="p-5"):
                with Row(justify="between", align="center"):
                    with Row(gap=2, align="center"):
                        Heading(f"{emoji} {input.organ.title()}", level=3)
                        Badge(f"{input.organ_score}/100", variant=rank_variant[rank])
                    Badge(f"Priority #{input.priority_rank}", variant="outline")

                Muted(f"{len(flagged)} flagged parameters", css_class="mt-1")
                Separator(css_class="my-3")

                if chart_data:
                    BarChart(
                        data=chart_data,
                        series=[ChartSeries(data_key="value", label="Your Value")],
                        x_axis="name",
                    )

                for category in ["diet", "exercise", "supplements"]:
                    recs = input.recommendations.get(category, [])
                    if recs:
                        Heading(category.title(), level=4)
                        for rec in recs:
                            Text(f"• {rec['title']}: {rec['description']}", css_class="mb-1")

                disclaimer = input.recommendations.get("disclaimer", "")
                if disclaimer:
                    Muted(disclaimer)

    return {
        "organ": input.organ,
        "priority_rank": input.priority_rank,
        "organ_score": input.organ_score,
        "component": section,
    }


def prioritize_organs_fn(input: PrioritizeOrgansInput) -> list[dict]:
    scored = sorted(
        input.organ_summaries,
        key=lambda s: s.get("flagged_count", 0),
        reverse=True,
    )
    return [
        {
            "organ": s["organ"],
            "priority": i,
            "reason": f"{s.get('flagged_count', 0)} flagged parameters",
        }
        for i, s in enumerate(scored[:4], 1)
    ]


def finish_dashboard_fn(input: FinishDashboardInput) -> dict:
    return {"status": "done", "sections": input.sections_complete, "summary": input.overall_summary}


# ── MCP registration ──────────────────────────────────────────────────────────

def register(mcp, get_store, get_mapper, get_client):

    @mcp.tool()
    def get_params_by_organ(input: GetParamsByOrganInput) -> dict:
        """
        Fetch all parameter values, reference ranges, readings, organ score, and flagged count for one organ.

        Returns organ name, organ_score (0–100), flagged_count, and a parameters list where each
        entry contains name, unit, ref_min, ref_max, organ, and a readings list (newest first).
        Use this to inspect raw lab data before building recommendations or UI sections.
        Also callable internally by the health agent during analysis.
        """
        return get_params_by_organ_fn(input, get_store(), get_mapper())

    @mcp.tool()
    def get_recommendations_for_case(input: GetRecommendationsForCaseInput) -> dict:
        """
        Get goal-aware AI recommendations for flagged parameters in one organ.

        Returns a dict with diet, exercise, supplements (up to 3 each), quest_titles, and a disclaimer.
        Recommendations are tailored to the user's use_case (e.g. "weight loss", "general wellness").
        Results are cached per (patient_id, organ, flagged_parameter_names).
        Only generates recommendations for parameters listed in flagged_parameter_names.
        """
        return get_recommendations_for_case_fn(input, get_store(), get_client())

    @mcp.tool(app=True)
    def build_organ_ui_section(input: BuildOrganUISectionInput):
        """
        Build a Prefab UI card for one organ using pre-fetched parameters and recommendations.

        Renders: organ score badge, bar chart of parameter values, and recommendations by category.
        Takes the output of get_params_by_organ (parameters) and get_recommendations_for_case (recommendations)
        as direct inputs — call those tools first. Used internally by the health agent; can also be
        called directly to render a standalone organ card.
        """
        return build_organ_ui_section_fn(input, get_mapper())

    @mcp.tool()
    def prioritize_organs(input: PrioritizeOrgansInput) -> list[dict]:
        """
        Rank organ systems by severity (flagged parameter count) to decide analysis order.

        Returns up to 4 organs sorted by flagged_count descending, each with organ name, priority rank,
        and reason string. Pass the organ_summaries list from run_health_agent context.
        The agent calls this first to decide which organs to analyse.
        """
        return prioritize_organs_fn(input)

    @mcp.tool()
    def finish_dashboard(input: FinishDashboardInput) -> dict:
        """
        Signal that the agent has finished building all organ sections.

        Returns a status dict confirming completion. The agent calls this as its final step after
        build_organ_ui_section has been called for all prioritised organs. Returns:
        status="done", sections=<count>, summary=<overall_summary_text>.
        """
        return finish_dashboard_fn(input)
```

- [ ] **Step 2: Run the tests**

```bash
uv run pytest tests/test_agent_mcp_tools.py -v
```

Expected: all tests PASS

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add agent/mcp_tools.py tests/test_agent_mcp_tools.py
git commit -m "feat: agent/mcp_tools with Pydantic models, standalone functions, MCP registration"
```

---

## Task 4: Update `agent/tools.py` to wrap `agent/mcp_tools.py`

**Files:**
- Modify: `agent/tools.py`

- [ ] **Step 1: Replace `agent/tools.py` entirely**

The old file contained inline closures with hand-written JSON Schema dicts. Replace with wrappers around the standalone functions:

```python
from llm.gemini import AgentTool
from core.organs import OrganMapper
from db.store import Store
from agent.mcp_tools import (
    GetParamsByOrganInput,
    GetParamsByOrganAgentInput,
    GetRecommendationsForCaseInput,
    GetRecommendationsForCaseAgentInput,
    BuildOrganUISectionInput,
    PrioritizeOrgansInput,
    FinishDashboardInput,
    get_params_by_organ_fn,
    get_recommendations_for_case_fn,
    build_organ_ui_section_fn,
    prioritize_organs_fn,
    finish_dashboard_fn,
)


def make_agent_tools(store: Store, mapper: OrganMapper, client, patient_id: str) -> list[AgentTool]:
    return [
        AgentTool(
            name="prioritize_organs",
            description="Decide which organ systems to investigate first based on severity and user context.",
            parameters=PrioritizeOrgansInput.model_json_schema(),
            fn=lambda **kwargs: prioritize_organs_fn(PrioritizeOrgansInput(**kwargs)),
        ),
        AgentTool(
            name="get_params_by_organ",
            description="Fetch all parameter values, reference ranges, and readings for an organ system.",
            parameters=GetParamsByOrganAgentInput.model_json_schema(),
            fn=lambda organ: get_params_by_organ_fn(
                GetParamsByOrganInput(patient_id=patient_id, organ=organ),
                store, mapper,
            ),
        ),
        AgentTool(
            name="get_recommendations_for_case",
            description="Get goal-aware AI recommendations for flagged parameters in an organ.",
            parameters=GetRecommendationsForCaseAgentInput.model_json_schema(),
            fn=lambda organ, use_case, flagged_parameter_names, severity: get_recommendations_for_case_fn(
                GetRecommendationsForCaseInput(
                    patient_id=patient_id,
                    organ=organ,
                    use_case=use_case,
                    flagged_parameter_names=flagged_parameter_names,
                    severity=severity,
                ),
                store, client,
            ),
        ),
        AgentTool(
            name="build_organ_ui_section",
            description="Build the Prefab UI section card for one organ using fetched data and recommendations.",
            parameters=BuildOrganUISectionInput.model_json_schema(),
            fn=lambda **kwargs: build_organ_ui_section_fn(
                BuildOrganUISectionInput(**kwargs), mapper
            ),
        ),
        AgentTool(
            name="finish_dashboard",
            description="Signal that all organ sections are complete. Call this last.",
            parameters=FinishDashboardInput.model_json_schema(),
            fn=lambda **kwargs: finish_dashboard_fn(FinishDashboardInput(**kwargs)),
        ),
    ]
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS (agent/runner.py uses `make_agent_tools()` which still works)

- [ ] **Step 3: Commit**

```bash
git add agent/tools.py
git commit -m "refactor: agent/tools make_agent_tools wraps agent/mcp_tools standalone functions"
```

---

## Task 5: Register agent MCP tools in `server.py`

**Files:**
- Modify: `server.py`

- [ ] **Step 1: Update `server.py`**

Add the import and registration. In `server.py`, after the existing `import agent.runner as agent_app` line:

```python
import agent.mcp_tools as agent_mcp_app
```

And after `agent_app.register(mcp, get_store, get_mapper, get_client)`:

```python
agent_mcp_app.register(mcp, get_store, get_mapper, get_client)
```

The full updated registration block in `server.py` should read:

```python
ingest_app.register(mcp, get_store, get_parser, get_mapper)
dashboard_app.register(mcp, get_store, get_mapper)
organ_panel_app.register(mcp, get_store, get_mapper, get_client)
charts_app.register(mcp, get_store, get_mapper)
recs_app.register(mcp, get_store, get_client)
quests_app.register(mcp, get_store, get_mapper)
inspector_app.register(mcp, get_store, get_mapper)
query_app.register(mcp, get_store, get_mapper)
agent_app.register(mcp, get_store, get_mapper, get_client)
agent_mcp_app.register(mcp, get_store, get_mapper, get_client)
```

- [ ] **Step 2: Verify server imports cleanly**

```bash
uv run python -c "import server; print('OK')"
```

Expected: `OK` with no errors

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat: register agent tools as MCP tools in server.py"
```

---

## Task 6: Pydantic on `apps/ingest.py`, `apps/dashboard.py`, `apps/query.py`

**Files:**
- Modify: `apps/ingest.py`, `apps/dashboard.py`, `apps/query.py`

- [ ] **Step 1: Establish test baseline**

```bash
uv run pytest -v
```

Note the number of passing tests — they must all still pass after this task.

- [ ] **Step 2: Update `apps/ingest.py`**

At the top of the file, add one import after the existing imports:
```python
from pydantic import BaseModel
```

Before the `register()` function, add:
```python
class UploadReportInput(BaseModel):
    patient_id: str | None = None
    patient_name: str | None = None
    file_path: str | None = None
    data: list[dict] | None = None
```

Inside `register()`, change `def upload_report(patient_id, patient_name, file_path, data)` to:
```python
    @mcp.tool()
    def upload_report(input: UploadReportInput) -> str:
        """
        Ingest a lab report for a patient and store all parameters with their reference ranges.

        Call this FIRST before any other tool — no data exists until a report is uploaded.
        Creates a new patient record if patient_id is omitted (returns the new patient_id in the response).
        Subsequent uploads for the same patient accumulate readings — existing parameters are updated, not duplicated.

        Parameters:
        - patient_id: omit on first upload; required for all subsequent uploads
        - patient_name: required only on first upload (used to create the patient record)
        - file_path: absolute path to a PDF lab report on disk
        - data: pre-parsed list of parameter dicts (use instead of file_path for JSON input)

        Provide exactly one of file_path or data. Returns a confirmation string with patient_id and parameter count.
        """
        return ingest_report(
            store=get_store(), parser=get_parser(), mapper=get_mapper(),
            patient_id=input.patient_id, patient_name=input.patient_name,
            file_path=input.file_path, data=input.data,
        )
```

- [ ] **Step 3: Update `apps/dashboard.py`**

Add the import at the top of the file (after existing imports):
```python
from pydantic import BaseModel
```

Add the model class before `register()`:
```python
class ShowHealthDashboardInput(BaseModel):
    patient_id: str
```

Update the tool function signature and body — change `def show_health_dashboard(patient_id: str):` to:
```python
    @mcp.tool(app=True)
    def show_health_dashboard(input: ShowHealthDashboardInput):
        """...(keep existing docstring unchanged)..."""
        from prefab_ui import PrefabApp
        from prefab_ui.components import (
            Column, Row, Card, CardContent, CardHeader, CardTitle,
            Grid, Badge, Text, Heading, Progress, Separator, Muted
        )

        store = get_store()
        mapper = get_mapper()
        patient_id = input.patient_id
        summaries = _build_organ_summaries(store, mapper, patient_id)
        # rest of body is unchanged — replace bare `patient_id` references with `input.patient_id`
        # (only affects the no-data branch: f"No reports found for patient {patient_id}.")
```

The simplest diff: add `patient_id = input.patient_id` as the first line inside the function body, so all existing `patient_id` references work unchanged.

- [ ] **Step 4: Update `apps/query.py`**

Add `from pydantic import BaseModel` at the top. Add three models and update the three tool functions:

```python
from pydantic import BaseModel

class ListOrgansInput(BaseModel):
    patient_id: str

class GetOrganParametersInput(BaseModel):
    patient_id: str
    organ: str

class GetPatientSummaryInput(BaseModel):
    patient_id: str
```

For each tool function, change the signature and add `patient_id = input.patient_id` / `organ = input.organ` extraction at the top of the body. Example for `list_organs`:

```python
    @mcp.tool()
    def list_organs(input: ListOrgansInput) -> list[dict]:
        """...(keep docstring)..."""
        patient_id = input.patient_id
        log.info("list_organs called — patient_id=%r", patient_id)
        store: Store = get_store()
        mapper: OrganMapper = get_mapper()
        # rest of body unchanged
```

Apply the same pattern to `get_organ_parameters` (extract `patient_id = input.patient_id; organ = input.organ`) and `get_patient_summary` (extract `patient_id = input.patient_id`).

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest -v
```

Expected: same number of tests passing as the baseline from Step 1.

- [ ] **Step 6: Commit**

```bash
git add apps/ingest.py apps/dashboard.py apps/query.py
git commit -m "feat: Pydantic input models for ingest, dashboard, query tools"
```

---

## Task 7: Pydantic on `apps/organ_panel.py`, `apps/charts.py`, `apps/quests.py`, `apps/recommendations.py`, `apps/inspector.py`

**Files:**
- Modify: `apps/organ_panel.py`, `apps/charts.py`, `apps/quests.py`, `apps/recommendations.py`, `apps/inspector.py`

The pattern for each file is identical to Task 6: add `from pydantic import BaseModel`, define a model, update the function signature, extract fields with `field = input.field` at the top of the body.

- [ ] **Step 1: Update `apps/organ_panel.py`**

Add after existing imports:
```python
from pydantic import BaseModel

class ShowOrganPanelInput(BaseModel):
    patient_id: str
    organ: str
```

Change `def show_organ_panel(patient_id: str, organ: str):` to:
```python
    def show_organ_panel(input: ShowOrganPanelInput):
```

Add at top of function body:
```python
        patient_id = input.patient_id
        organ = input.organ
```

- [ ] **Step 2: Update `apps/charts.py`**

Add after existing imports:
```python
from pydantic import BaseModel

class ShowBarComparisonInput(BaseModel):
    patient_id: str
    organ: str

class ShowGaugeChartInput(BaseModel):
    patient_id: str
    parameter: str

class ShowTrendChartInput(BaseModel):
    patient_id: str
    organs: list[str] | None = None
    lookback: int = 5
```

For `show_bar_comparison`: change signature to `(input: ShowBarComparisonInput)`, add `patient_id = input.patient_id; organ = input.organ` at top of body.

For `show_gauge_chart`: change signature to `(input: ShowGaugeChartInput)`, add `patient_id = input.patient_id; parameter = input.parameter` at top of body.

For `show_trend_chart`: change signature to `(input: ShowTrendChartInput)`, add at top of body:
```python
        patient_id = input.patient_id
        organs = input.organs
        lookback = input.lookback
```
Remove the existing `if isinstance(organs, str): organs = [organs]` line (no longer needed; Pydantic enforces `list[str] | None`).

- [ ] **Step 3: Update `apps/quests.py`**

Add after existing imports:
```python
from pydantic import BaseModel

class ShowActiveQuestsInput(BaseModel):
    patient_id: str
```

Change `def show_active_quests(patient_id: str):` to `def show_active_quests(input: ShowActiveQuestsInput):`, add `patient_id = input.patient_id` at top of body.

- [ ] **Step 4: Update `apps/recommendations.py`**

Add after existing imports:
```python
from pydantic import BaseModel

class GetRecommendationsInput(BaseModel):
    patient_id: str
    organ: str
```

Change `def get_recommendations(patient_id: str, organ: str) -> str:` to `def get_recommendations(input: GetRecommendationsInput) -> str:`, add `patient_id = input.patient_id; organ = input.organ` at top of body.

- [ ] **Step 5: Update `apps/inspector.py`**

Add after existing imports:
```python
from pydantic import BaseModel

class ShowInspectorInput(BaseModel):
    patient_id: str = ""
```

Change `def show_inspector(patient_id: str = ""):` to `def show_inspector(input: ShowInspectorInput):`, add `patient_id = input.patient_id` at top of body.

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS

- [ ] **Step 7: Verify server starts cleanly**

```bash
uv run python -c "import server; print('server loaded OK')"
```

Expected: `server loaded OK`

- [ ] **Step 8: Commit**

```bash
git add apps/organ_panel.py apps/charts.py apps/quests.py apps/recommendations.py apps/inspector.py
git commit -m "feat: Pydantic input models for organ_panel, charts, quests, recommendations, inspector tools"
```
