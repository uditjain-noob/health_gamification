from pydantic import BaseModel
from core.scorer import score_parameter, score_organ, get_difficulty
from core.organs import OrganMapper
from db.store import Store


class ShowOrganPanelInput(BaseModel):
    patient_id: str
    organ: str


def register(mcp, get_store, get_mapper, get_client):
    @mcp.tool(app=True)
    def show_organ_panel(input: ShowOrganPanelInput):
        """
        Show a detailed panel for a single organ system with scores, parameter table, and AI recommendations.

        Renders: organ score badge, AI-generated 1-2 sentence summary, full parameter data table
        (value, normal range, status, delta from midpoint), Ring gauges for flagged parameters,
        and tabbed diet / exercise / supplement recommendations.

        Use this when a user asks about a specific organ ("how is my liver?", "what's wrong with my heart?")
        or after show_health_dashboard to drill into a low-scoring organ.
        Organ name is case-insensitive. Call list_organs first to see available organ names.

        Parameters:
        - patient_id: the patient's ID
        - organ: organ name (e.g. "liver", "heart", "kidney") — case-insensitive
        """
        patient_id = input.patient_id
        organ = input.organ
        from prefab_ui import PrefabApp
        from prefab_ui.components import (
            Column, Row, Card, CardContent, CardHeader, CardTitle,
            Badge, Text, Heading, Separator, Tabs, Tab,
            Muted, DataTable, DataTableColumn
        )
        from prefab_ui.components import Ring, Metric

        store = get_store()
        mapper = get_mapper()
        client = get_client()

        params = store.get_parameters_for_organ(patient_id, organ)
        if not params:
            with Column() as view:
                Text(f"No data for organ: {organ}")
            return PrefabApp(view=view)

        critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
        organ_score = score_organ(params, critical)
        flagged = [p for p in params if p["readings"] and p["readings"][0]["status"] != "normal"]

        # AI summary (short, one-shot)
        summary_prompt = (
            f"In 1-2 sentences, summarize the {organ} health based on these flagged markers: "
            f"{[p['name'] for p in flagged]}. Be encouraging, not alarming. No diagnosis."
        )
        if flagged:
            try:
                summary = client.complete(system="You are a wellness assistant.", user=summary_prompt)
            except Exception:
                summary = f"Some {organ} markers need attention. Review the table below for details."
        else:
            summary = f"All {organ} markers are within normal range. Keep it up!"

        # Build table rows
        table_data = []
        for p in params:
            if not p["readings"]:
                continue
            r = p["readings"][0]
            midpoint = (p["ref_min"] + p["ref_max"]) / 2
            delta = round(r["value"] - midpoint, 2)
            status_variant = {"normal": "success", "high": "destructive", "low": "warning"}
            table_data.append({
                "parameter": p["name"],
                "value": f"{r['value']} {p['unit']}",
                "range": f"{p['ref_min']} – {p['ref_max']}",
                "status": r["status"],
                "delta": f"{'+' if delta >= 0 else ''}{delta}",
            })

        # Get recommendations
        from apps.recommendations import fetch_recommendations
        try:
            recs = fetch_recommendations(client, organ, flagged, patient_id)
        except Exception:
            recs = {"diet": [], "exercise": [], "supplements": []}

        emoji = mapper.get_organ_emoji(organ)
        rank_variant = {"Optimal": "success", "Good": "default", "At Risk": "warning", "Critical": "destructive"}
        rank = "Optimal" if organ_score >= 90 else "Good" if organ_score >= 70 else "At Risk" if organ_score >= 50 else "Critical"

        with Column(gap=6, css_class="p-6") as view:
            with Card():
                with CardContent(css_class="p-5"):
                    with Row(justify="between", align="center"):
                        Heading(f"{emoji} {organ.title()}", level=2)
                        with Row(gap=2):
                            Badge(f"{organ_score}/100", variant="outline")
                            Badge(rank, variant=rank_variant[rank])
                    Muted(summary, css_class="mt-2")

            DataTable(
                rows=table_data,
                columns=[
                    DataTableColumn(key="parameter", header="Parameter"),
                    DataTableColumn(key="value", header="Value"),
                    DataTableColumn(key="range", header="Normal Range"),
                    DataTableColumn(key="status", header="Status"),
                    DataTableColumn(key="delta", header="Δ from Mid"),
                ],
            )

            if flagged:
                Heading("Out-of-Range Parameters", level=4)
                with Row(gap=4, css_class="flex-wrap"):
                    for p in flagged:
                        r = p["readings"][0]
                        ring_val = min(100, round(
                            score_parameter(r["value"], p["ref_min"], p["ref_max"])
                        ))
                        with Column(align="center", gap=2):
                            Ring(value=ring_val, max=100)
                            Metric(label=p["name"], value=f"{r['value']} {p['unit']}")

            with Tabs(value="diet"):
                with Tab("Diet"):
                    for rec in recs.get("diet", []):
                        Text(f"• {rec['title']}: {rec['description']}", css_class="mb-2")
                with Tab("Exercise"):
                    for rec in recs.get("exercise", []):
                        Text(f"• {rec['title']}: {rec['description']}", css_class="mb-2")
                with Tab("Supplements"):
                    for rec in recs.get("supplements", []):
                        Text(f"• {rec['title']}: {rec['description']}", css_class="mb-2")
                    Muted("Note: These are general wellness suggestions, not medical advice.")

        return PrefabApp(view=view)
