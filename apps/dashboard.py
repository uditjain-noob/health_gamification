from pydantic import BaseModel
from core.scorer import score_parameter, score_organ, score_overall, get_rank, get_level
from core.organs import OrganMapper
from db.store import Store

ORGAN_RANK_MAP = {
    (90, 101): "Optimal", (70, 90): "Good", (50, 70): "At Risk", (0, 50): "Critical"
}

RANK_EMOJI = {"Bronze": "🟤", "Silver": "⚪", "Gold": "🟡", "Platinum": "🔵", "Diamond": "💎"}

def _organ_rank(score: int) -> str:
    for (lo, hi), rank in ORGAN_RANK_MAP.items():
        if lo <= score < hi:
            return rank
    return "Critical"

def _build_organ_summaries(store: Store, mapper: OrganMapper, patient_id: str) -> list[dict]:
    summaries = []
    for row in store.get_organ_summaries(patient_id):
        organ = row["organ"]
        params = store.get_parameters_for_organ(patient_id, organ)
        if not params:
            continue
        critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
        score = score_organ(params, critical)
        flagged = sum(
            1 for p in params
            if p["readings"] and p["readings"][0]["status"] != "normal"
        )
        summaries.append({
            "organ": organ,
            "score": score,
            "flagged_count": flagged,
            "parameter_count": len(params),
            "rank": _organ_rank(score),
            "emoji": mapper.get_organ_emoji(organ),
            "weight": mapper.get_organ_weight(organ),
        })
    return summaries


def get_dashboard_json(store: Store, mapper: OrganMapper, patient_id: str) -> dict:
    """Return dashboard summary as plain JSON (overall score, rank, level, XP, organ list)."""
    summaries = _build_organ_summaries(store, mapper, patient_id)
    if not summaries:
        xp_total = store.get_xp_total(patient_id)
        return {
            "overall": 0, "rank": "Bronze", "rank_emoji": "🟤",
            "level": 1, "xp_total": xp_total, "xp_to_next": 50,
            "organs": [], "total_params": 0, "total_flagged": 0,
        }
    organ_scores = {s["organ"]: s["score"] for s in summaries}
    organ_weights = {s["organ"]: s["weight"] for s in summaries}
    overall = score_overall(organ_scores, organ_weights)
    rank = get_rank(overall)
    level = get_level(overall)
    xp_total = store.get_xp_total(patient_id)
    xp_to_next = max(0, (level + 1) * 50 - xp_total)
    rank_emoji = RANK_EMOJI.get(rank, "🟤")
    total_params = sum(s["parameter_count"] for s in summaries)
    total_flagged = sum(s["flagged_count"] for s in summaries)
    return {
        "overall": overall,
        "rank": rank,
        "rank_emoji": rank_emoji,
        "level": level,
        "xp_total": xp_total,
        "xp_to_next": xp_to_next,
        "organs": [
            {
                "organ": s["organ"],
                "emoji": s["emoji"],
                "score": s["score"],
                "rank": s["rank"],
                "flagged_count": s["flagged_count"],
                "parameter_count": s["parameter_count"],
            }
            for s in summaries
        ],
        "total_params": total_params,
        "total_flagged": total_flagged,
    }


class ShowHealthDashboardInput(BaseModel):
    patient_id: str


def register(mcp, get_store, get_mapper):
    @mcp.tool(app=True)
    def show_health_dashboard(input: ShowHealthDashboardInput):
        """
        Show the top-level gamified health dashboard for a patient.

        Renders a visual overview of all organ systems with scores (0–100), rank badges,
        XP total, health level, and a grid of organ cards sorted by score.
        Use this as the entry point when a user asks "how am I doing?" or wants a health overview.
        Drill into a specific organ with show_organ_panel; see raw scores with get_patient_summary.

        Requires: patient_id (use list_organs to see what organs have data).
        """
        patient_id = input.patient_id
        from prefab_ui import PrefabApp
        from prefab_ui.components import (
            Column, Row, Card, CardContent, CardHeader, CardTitle,
            Grid, Badge, Text, Heading, Progress, Separator, Muted
        )

        store = get_store()
        mapper = get_mapper()
        summaries = _build_organ_summaries(store, mapper, patient_id)

        if not summaries:
            with Column(gap=4) as view:
                Heading("No data found")
                Text(f"No reports found for patient {patient_id}. Use upload_report first.")
            return PrefabApp(view=view)

        organ_scores = {s["organ"]: s["score"] for s in summaries}
        organ_weights = {s["organ"]: s["weight"] for s in summaries}
        overall = score_overall(organ_scores, organ_weights)
        rank = get_rank(overall)
        level = get_level(overall)
        xp_total = store.get_xp_total(patient_id)
        xp_to_next = max(0, (level + 1) * 50 - xp_total)

        rank_emoji = RANK_EMOJI.get(rank, "🟤")
        rank_variant = {"Optimal": "success", "Good": "default", "At Risk": "warning", "Critical": "destructive"}

        with Column(gap=6, css_class="p-6") as view:
            with Card():
                with CardContent(css_class="p-5"):
                    with Row(justify="between", align="center"):
                        Heading(f"{rank_emoji} {rank} Health Champion", level=2)
                        Badge(f"Level {level}", variant="outline")
                    Text(f"Overall Score: {overall}/1000", css_class="text-2xl font-bold mt-2")
                    Progress(value=xp_total % 50, max=50, css_class="mt-3")
                    Muted(f"{xp_to_next} XP to next level")

            Heading("Organ Systems", level=3)
            with Grid(columns=3, gap=4):
                for s in summaries:
                    with Card():
                        with CardContent(css_class="p-4"):
                            with Row(justify="between", align="center"):
                                Text(f"{s['emoji']} {s['organ'].title()}", css_class="font-semibold")
                                Badge(s["rank"], variant=rank_variant.get(s["rank"], "default"))
                            Text(f"{s['score']}/100", css_class="text-xl font-bold mt-1")
                            Muted(f"{s['flagged_count']} flagged / {s['parameter_count']} total")

            Separator()
            with Row(gap=6):
                total_params = sum(s["parameter_count"] for s in summaries)
                total_flagged = sum(s["flagged_count"] for s in summaries)
                Muted(f"📊 {total_params} parameters checked")
                Muted(f"🚩 {total_flagged} flagged")
                Muted(f"✅ {total_params - total_flagged} in range")

        return PrefabApp(view=view)

    class GetDashboardDataInput(BaseModel):
        patient_id: str

    @mcp.tool()
    def get_dashboard_data(input: GetDashboardDataInput) -> dict:
        """Return dashboard summary as plain JSON (overall score, rank, level, XP, organ list)."""
        return get_dashboard_json(get_store(), get_mapper(), input.patient_id)
