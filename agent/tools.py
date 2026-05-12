import json
from llm.gemini import AgentTool
from core.scorer import score_parameter, score_organ, get_difficulty
from core.organs import OrganMapper
from db.store import Store

PHASE1_ORGANS = ["liver", "kidney", "blood", "metabolic"]

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


def make_agent_tools(store: Store, mapper: OrganMapper, client, patient_id: str) -> list[AgentTool]:

    def prioritize_organs(context: str, organ_summaries: list) -> list:
        scored = []
        for s in organ_summaries:
            priority_score = s.get("flagged_count", 0) * 10
            scored.append({**s, "priority_score": priority_score})
        scored.sort(key=lambda x: x["priority_score"], reverse=True)
        result = []
        for i, s in enumerate(scored[:4], 1):
            result.append({
                "organ": s["organ"],
                "priority": i,
                "reason": f"{s.get('flagged_count', 0)} flagged parameters",
            })
        return result

    def get_params_by_organ(organ: str) -> dict:
        params = store.get_parameters_for_organ(patient_id, organ)
        critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
        organ_score = score_organ(params, critical)
        flagged_count = sum(
            1 for p in params if p["readings"] and p["readings"][0]["status"] != "normal"
        )
        return {
            "organ": organ,
            "parameters": params,
            "organ_score": organ_score,
            "flagged_count": flagged_count,
        }

    def get_recommendations_for_case(organ: str, use_case: str, flagged_parameter_names: list, severity: str) -> dict:
        cache_key = (organ, use_case, tuple(sorted(flagged_parameter_names)))
        if cache_key in _CASE_REC_CACHE:
            return _CASE_REC_CACHE[cache_key]

        params = store.get_parameters_for_organ(patient_id, organ)
        flagged = [p for p in params if p["name"] in flagged_parameter_names]
        if not flagged:
            return {"diet": [], "exercise": [], "supplements": [], "quest_titles": [], "disclaimer": ""}

        flagged_text = "\n".join(
            f"- {p['name']}: {p['readings'][0]['value']} {p['unit']} (normal: {p['ref_min']}–{p['ref_max']})"
            for p in flagged if p.get("readings")
        )
        try:
            raw = client.complete(
                system="You are a health optimization assistant. Return ONLY valid JSON.",
                user=_CASE_REC_PROMPT.format(
                    use_case=use_case or "general wellness",
                    organ=organ, flagged=flagged_text, severity=severity
                ),
            )
            result = json.loads(raw)
        except Exception:
            result = {"diet": [], "exercise": [], "supplements": [], "quest_titles": [], "disclaimer": ""}
        _CASE_REC_CACHE[cache_key] = result
        return result

    def build_organ_ui_section(
        organ: str, organ_score: int, parameters: list,
        recommendations: dict, priority_rank: int
    ) -> dict:
        """Build a Prefab UI section Card for one organ. Returns a serialized block."""
        from prefab_ui.components import (
            Column, Row, Card, CardContent, Heading, Text, Badge, Separator, Muted
        )
        from prefab_ui.components import Ring
        from prefab_ui.components.charts import BarChart, ChartSeries

        rank = "Optimal" if organ_score >= 90 else "Good" if organ_score >= 70 else "At Risk" if organ_score >= 50 else "Critical"
        rank_variant = {"Optimal": "success", "Good": "default", "At Risk": "warning", "Critical": "destructive"}
        emoji = mapper.get_organ_emoji(organ)
        flagged = [p for p in parameters if p.get("readings") and p["readings"][0]["status"] != "normal"]

        chart_data = [
            {"name": p["name"], "value": p["readings"][0]["value"]}
            for p in parameters if p.get("readings")
        ]

        with Column(gap=4) as section:
            with Card():
                with CardContent(css_class="p-5"):
                    with Row(justify="between", align="center"):
                        with Row(gap=2, align="center"):
                            Heading(f"{emoji} {organ.title()}", level=3)
                            Badge(f"{organ_score}/100", variant=rank_variant[rank])
                        Badge(f"Priority #{priority_rank}", variant="outline")

                    Muted(f"{len(flagged)} flagged parameters", css_class="mt-1")
                    Separator(css_class="my-3")

                    if chart_data:
                        BarChart(
                            data=chart_data,
                            series=[ChartSeries(data_key="value", label="Your Value")],
                            x_axis="name",
                        )

                    # Recommendations — use plain Text blocks instead of Tabs if Tabs API is different
                    for category in ["diet", "exercise", "supplements"]:
                        recs = recommendations.get(category, [])
                        if recs:
                            Heading(category.title(), level=5)
                            for rec in recs:
                                Text(f"• {rec['title']}: {rec['description']}", css_class="mb-1")
                    disclaimer = recommendations.get("disclaimer", "")
                    if disclaimer:
                        Muted(disclaimer)

        return {"organ": organ, "priority_rank": priority_rank, "component": section}

    def finish_dashboard(sections_complete: int, overall_summary: str) -> dict:
        return {"status": "done", "sections": sections_complete, "summary": overall_summary}

    return [
        AgentTool(
            name="prioritize_organs",
            description="Decide which organ systems to investigate first based on severity and user context.",
            parameters={
                "type": "object",
                "properties": {
                    "context": {"type": "string", "description": "User goal or focus area"},
                    "organ_summaries": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of organ summary dicts with organ, score, flagged_count",
                    },
                },
                "required": ["context", "organ_summaries"],
            },
            fn=prioritize_organs,
        ),
        AgentTool(
            name="get_params_by_organ",
            description="Fetch all parameter values, reference ranges, and readings for an organ system.",
            parameters={
                "type": "object",
                "properties": {"organ": {"type": "string", "description": "Organ name, e.g. 'liver'"}},
                "required": ["organ"],
            },
            fn=get_params_by_organ,
        ),
        AgentTool(
            name="get_recommendations_for_case",
            description="Get goal-aware AI recommendations for flagged parameters in an organ.",
            parameters={
                "type": "object",
                "properties": {
                    "organ": {"type": "string"},
                    "use_case": {"type": "string", "description": "User goal, e.g. 'weight loss'"},
                    "flagged_parameter_names": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Names of flagged parameters",
                    },
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["organ", "use_case", "flagged_parameter_names", "severity"],
            },
            fn=get_recommendations_for_case,
        ),
        AgentTool(
            name="build_organ_ui_section",
            description="Build the Prefab UI section card for one organ using fetched data and recommendations.",
            parameters={
                "type": "object",
                "properties": {
                    "organ": {"type": "string"},
                    "organ_score": {"type": "integer"},
                    "parameters": {"type": "array", "items": {"type": "object"}},
                    "recommendations": {"type": "object"},
                    "priority_rank": {"type": "integer"},
                },
                "required": ["organ", "organ_score", "parameters", "recommendations", "priority_rank"],
            },
            fn=build_organ_ui_section,
        ),
        AgentTool(
            name="finish_dashboard",
            description="Signal that all organ sections are complete. Call this last.",
            parameters={
                "type": "object",
                "properties": {
                    "sections_complete": {"type": "integer"},
                    "overall_summary": {"type": "string"},
                },
                "required": ["sections_complete", "overall_summary"],
            },
            fn=finish_dashboard,
        ),
    ]
