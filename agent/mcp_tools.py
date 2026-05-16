from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from core.scorer import score_organ, score_parameter
from core.organs import OrganMapper
from db.store import Store

log = logging.getLogger("healthquest.agent.mcp_tools")


# ── Pydantic input models (MCP — include patient_id) ─────────────────────────

class GetParamsByOrganInput(BaseModel):
    patient_id: str = Field(description="Patient UUID from upload_report")
    organ: str = Field(description="Organ name, e.g. 'liver', 'heart'")


class BuildOrganUISectionInput(BaseModel):
    patient_id: str = Field(description="Patient UUID from upload_report")
    organ: str = Field(description="Organ name")
    organ_score: int = Field(description="Organ score 0–100")
    recommendations: dict = Field(description="Recommendations dict from get_rag_recommendations")
    priority_rank: int = Field(description="Organ priority rank (1 = highest)")


class PrioritizeOrgansInput(BaseModel):
    context: str = Field(default="", description="User goal or focus area")
    organ_summaries: list[dict] = Field(
        description="List of organ summaries with organ, score, flagged_count"
    )


class FinishDashboardInput(BaseModel):
    sections_complete: int = Field(description="Number of organ sections built")
    overall_summary: str = Field(description="1-2 sentence overall health summary")


# ── Agent-facing models (no patient_id — Gemini doesn't need to supply it) ───

class GetParamsByOrganAgentInput(BaseModel):
    organ: str = Field(description="Organ name, e.g. 'liver', 'heart'")


class BuildOrganUISectionAgentInput(BaseModel):
    organ: str = Field(description="Organ name")
    organ_score: int = Field(description="Organ score 0–100, from get_params_by_organ result")
    recommendations: dict = Field(description="Recommendations dict from get_rag_recommendations")
    priority_rank: int = Field(description="Organ priority rank (1 = highest), from prioritize_organs result")


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


def build_organ_ui_section_fn(
    input: BuildOrganUISectionInput,
    store: Store,
    mapper: OrganMapper,
) -> dict:
    from prefab_ui.components import (
        Column, Row, Grid, Card, CardContent, Heading, Badge, Separator, Muted, Metric,
    )
    from prefab_ui.components.charts import Sparkline

    rank = (
        "Optimal" if input.organ_score >= 90
        else "Good" if input.organ_score >= 70
        else "At Risk" if input.organ_score >= 50
        else "Critical"
    )
    rank_variant = {"Optimal": "success", "Good": "default", "At Risk": "warning", "Critical": "destructive"}
    status_variant = {"high": "destructive", "low": "warning", "normal": "success"}
    emoji = mapper.get_organ_emoji(input.organ)

    params = store.get_parameters_for_organ(input.patient_id, input.organ)
    flagged = [p for p in params if p.get("readings") and p["readings"][0]["status"] != "normal"]

    with Column(gap=4) as section:
        with Card():
            with CardContent(css_class="p-5"):
                with Row(justify="between", align="center"):
                    with Row(gap=2, align="center"):
                        Heading(f"{emoji} {input.organ.title()}", level=3)
                        Badge(f"{input.organ_score}/100", variant=rank_variant[rank])
                    Badge(f"Priority #{input.priority_rank}", variant="outline")

                if flagged:
                    Muted(f"{len(flagged)} flagged parameter{'s' if len(flagged) != 1 else ''}", css_class="mt-1")
                    Separator(css_class="my-3")
                    with Grid(columns=2, gap=3):
                        for p in flagged:
                            readings = p.get("readings", [])
                            latest = readings[0]
                            with Card():
                                with CardContent(css_class="p-3"):
                                    Metric(
                                        label=p["name"],
                                        value=f"{latest['value']} {p['unit']}",
                                    )
                                    Badge(
                                        latest["status"].upper(),
                                        variant=status_variant.get(latest["status"], "default"),
                                        css_class="mt-1",
                                    )
                                    Muted(
                                        f"Normal: {p['ref_min']}–{p['ref_max']} {p['unit']}",
                                        css_class="text-xs mt-1",
                                    )
                                    if len(readings) > 1:
                                        scores = [
                                            score_parameter(r["value"], p["ref_min"], p["ref_max"])
                                            for r in reversed(readings)
                                        ]
                                        Sparkline(data=scores, css_class="mt-2 h-10")
                else:
                    Muted("All parameters in normal range ✓", css_class="mt-1")

                for category in ["diet", "exercise", "supplements"]:
                    recs = input.recommendations.get(category, [])
                    if recs:
                        Separator(css_class="my-3")
                        Heading(category.title(), level=5)
                        for rec in recs:
                            Muted(f"• {rec['title']}: {rec['description']}", css_class="mb-1")

                disclaimer = input.recommendations.get("disclaimer", "")
                if disclaimer:
                    Muted(disclaimer, css_class="mt-3 text-xs")

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
        """
        return get_params_by_organ_fn(input, get_store(), get_mapper())

    @mcp.tool(app=True)
    def build_organ_ui_section(input: BuildOrganUISectionInput):
        """
        Build a Prefab UI card for one organ — fetches its own parameter data from the database.

        Renders: organ score badge, Metric tiles for each flagged parameter (with Sparkline trend
        if multiple readings exist), and recommendations by category.
        Pass organ_score and priority_rank from get_params_by_organ / prioritize_organs results.
        Pass recommendations from get_rag_recommendations.
        """
        return build_organ_ui_section_fn(input, get_store(), get_mapper())

    @mcp.tool()
    def prioritize_organs(input: PrioritizeOrgansInput) -> list[dict]:
        """
        Rank organ systems by severity (flagged parameter count) to decide analysis order.

        Returns up to 4 organs sorted by flagged_count descending, each with organ name, priority rank,
        and reason string. The agent calls this first to decide which organs to analyse.
        """
        return prioritize_organs_fn(input)

    @mcp.tool()
    def finish_dashboard(input: FinishDashboardInput) -> dict:
        """
        Signal that the agent has finished building all organ sections.

        Returns status="done", sections=<count>, summary=<overall_summary_text>.
        Call this as the final step after build_organ_ui_section for all prioritised organs.
        """
        return finish_dashboard_fn(input)
