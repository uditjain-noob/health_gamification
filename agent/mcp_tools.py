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
    cache_key = (input.patient_id, input.organ, tuple(sorted(input.flagged_parameter_names)), input.use_case, input.severity)
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
        log.exception("LLM call failed for organ=%s patient=%s", input.organ, input.patient_id)
        return {"diet": [], "exercise": [], "supplements": [], "quest_titles": [], "disclaimer": ""}

    _CASE_REC_CACHE[cache_key] = result
    return result


def build_organ_ui_section_fn(
    input: BuildOrganUISectionInput,
    mapper: OrganMapper,
) -> dict:
    from prefab_ui.components import (
        Column, Row, Card, CardContent, Heading, Text, Badge, Separator, Muted,
    )
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
            "priority_rank": i,
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
