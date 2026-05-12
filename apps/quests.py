from core.scorer import get_difficulty, get_xp_for_difficulty
from core.organs import OrganMapper
from db.store import Store

PHASE1_ORGANS = ["liver", "kidney", "blood", "metabolic"]


def register(mcp, get_store, get_mapper):
    @mcp.tool(app=True)
    def show_active_quests(patient_id: str):
        """Show active health quests — one per out-of-range parameter."""
        from prefab_ui import PrefabApp
        from prefab_ui.components import (
            Column, Row, Card, CardContent, Heading,
            Badge, Text, Muted, Progress, Separator
        )

        store = get_store()
        mapper = get_mapper()

        quests = []
        total_params = 0
        for organ in PHASE1_ORGANS:
            params = store.get_parameters_for_organ(patient_id, organ)
            total_params += len(params)
            for p in params:
                if not p["readings"]:
                    continue
                r = p["readings"][0]
                if r["status"] == "normal":
                    continue
                difficulty = get_difficulty(r["value"], p["ref_min"], p["ref_max"])
                xp = get_xp_for_difficulty(difficulty)
                direction = "high" if r["status"] == "high" else "low"
                quests.append({
                    "name": f"{'Lower' if direction == 'high' else 'Raise'} Your {p['name']}",
                    "organ": organ,
                    "emoji": mapper.get_organ_emoji(organ),
                    "difficulty": difficulty,
                    "xp": xp,
                    "value": r["value"],
                    "ref_min": p["ref_min"],
                    "ref_max": p["ref_max"],
                    "unit": p["unit"],
                    "status": r["status"],
                })

        # Sort: Hard first
        difficulty_order = {"Hard": 0, "Medium": 1, "Easy": 2}
        quests.sort(key=lambda q: difficulty_order.get(q["difficulty"], 3))

        diff_variant = {"Hard": "destructive", "Medium": "warning", "Easy": "success"}
        status_variant = {"high": "destructive", "low": "warning"}
        resolved = total_params - len(quests)

        with Column(gap=6, css_class="p-6") as view:
            with Row(justify="between", align="center"):
                Heading("Active Quests", level=2)
                Badge(f"{len(quests)} active", variant="outline")

            Progress(value=resolved, max=max(total_params, 1), css_class="mb-2")
            Muted(f"{resolved}/{total_params} parameters in healthy range")

            Separator()

            if not quests:
                with Card():
                    with CardContent(css_class="p-5 text-center"):
                        Heading("🎉 All Clear!", level=3)
                        Text("All your parameters are within normal range.")
            else:
                for q in quests:
                    with Card(css_class="mb-3"):
                        with CardContent(css_class="p-4"):
                            with Row(justify="between", align="center"):
                                Text(f"{q['emoji']} {q['name']}", css_class="font-semibold")
                                with Row(gap=2):
                                    Badge(q["difficulty"], variant=diff_variant[q["difficulty"]])
                                    Badge(f"+{q['xp']} XP", variant="outline")
                            with Row(gap=2, css_class="mt-2"):
                                Badge(q["organ"].title(), variant="secondary")
                                Badge(
                                    f"Current: {q['value']} {q['unit']}",
                                    variant=status_variant.get(q["status"], "default"),
                                )
                                Muted(f"Target: {q['ref_min']}–{q['ref_max']}")

        return PrefabApp(view=view)
