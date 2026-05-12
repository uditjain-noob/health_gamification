from core.scorer import score_overall, get_rank, get_level
from core.organs import OrganMapper
from db.store import Store


def assemble_dashboard(
    ui_blocks: list[dict],
    patient_id: str,
    store: Store,
    mapper: OrganMapper,
    overall_summary: str = "",
):
    from prefab_ui import PrefabApp
    from prefab_ui.components import (
        Column, Row, Card, CardContent, Heading,
        Badge, Muted, Progress, Separator
    )

    xp_total = store.get_xp_total(patient_id)

    if ui_blocks:
        avg_score = round(sum(b.get("organ_score", 70) for b in ui_blocks) / len(ui_blocks))
        overall = min(1000, avg_score * 10)
    else:
        overall = 0

    rank = get_rank(overall)
    level = get_level(overall)
    rank_emoji = {"Bronze": "🟤", "Silver": "⚪", "Gold": "🟡", "Platinum": "🔵", "Diamond": "💎"}.get(rank, "🟤")

    with Column(gap=6, css_class="p-6") as layout:
        with Card():
            with CardContent(css_class="p-5"):
                with Row(justify="between", align="center"):
                    Heading(f"{rank_emoji} {rank} Health Champion — Level {level}", level=2)
                    Badge(f"Score: {overall}/1000", variant="outline")
                if overall_summary:
                    Muted(overall_summary, css_class="mt-2")
                Progress(value=xp_total % 50, max=50, css_class="mt-3")
                Muted(f"{xp_total} XP total")

        Separator()

        for block in ui_blocks:
            component = block.get("component")
            if component is not None:
                component

        Separator()
        Muted(
            "⚠️ These recommendations are general wellness suggestions, not medical advice. "
            "Consult a healthcare provider before making health decisions.",
            css_class="text-center"
        )

    return PrefabApp(view=layout)
