from core.scorer import score_parameter, get_difficulty
from core.organs import OrganMapper
from db.store import Store


def register(mcp, get_store, get_mapper):
    @mcp.tool(app=True)
    def show_bar_comparison(patient_id: str, organ: str):
        """Show a bar chart comparing all parameters for an organ, sorted by deviation."""
        from prefab_ui import PrefabApp
        from prefab_ui.components import Column, Row, Heading, Muted, Badge, Metric
        from prefab_ui.components.charts import BarChart, ChartSeries

        store = get_store()
        mapper = get_mapper()
        params = store.get_parameters_for_organ(patient_id, organ)

        if not params:
            with Column() as view:
                Muted(f"No data for organ: {organ}")
            return PrefabApp(view=view)

        chart_data = []
        for p in params:
            if not p["readings"]:
                continue
            value = p["readings"][0]["value"]
            score = score_parameter(value, p["ref_min"], p["ref_max"])
            deviation_pct = 0.0
            rw = p["ref_max"] - p["ref_min"]
            if rw > 0:
                dev = max(0.0, value - p["ref_max"], p["ref_min"] - value)
                deviation_pct = dev / rw
            chart_data.append({
                "name": p["name"],
                "value": value,
                "ref_min": p["ref_min"],
                "ref_max": p["ref_max"],
                "score": score,
                "deviation_pct": deviation_pct,
                "status": p["readings"][0]["status"],
            })

        # Sort worst first
        chart_data.sort(key=lambda x: x["deviation_pct"], reverse=True)

        status_variant = {"high": "destructive", "low": "warning", "normal": "success"}
        emoji = mapper.get_organ_emoji(organ)

        with Column(gap=4, css_class="p-6") as view:
            Heading(f"{emoji} {organ.title()} — Parameter Comparison", level=3)
            BarChart(
                data=chart_data,
                series=[ChartSeries(data_key="value", label="Your Value")],
                x_axis="name",
            )
            with Row(gap=3, css_class="flex-wrap mt-4"):
                for item in chart_data:
                    Badge(
                        f"{item['name']}: {item['value']}",
                        variant=status_variant.get(item["status"], "default"),
                    )

        return PrefabApp(view=view)

    @mcp.tool(app=True)
    def show_gauge_chart(patient_id: str, parameter: str):
        """Show a gauge (Ring) chart for a single parameter with trend sparkline."""
        from prefab_ui import PrefabApp
        from prefab_ui.components import Column, Row, Heading, Badge, Metric, Muted
        from prefab_ui.components import Ring
        from prefab_ui.components.charts import Sparkline

        store = get_store()
        all_params = store.get_all_parameters(patient_id)
        match = next(
            (p for p in all_params if p["name"].upper() == parameter.upper()), None
        )

        if not match:
            with Column() as view:
                Muted(f"Parameter '{parameter}' not found.")
            return PrefabApp(view=view)

        readings = match["readings"]
        latest = readings[0] if readings else None
        ref_min, ref_max = match["ref_min"], match["ref_max"]
        score = score_parameter(latest["value"], ref_min, ref_max) if latest else 0
        status = latest["status"] if latest else "normal"
        status_variant = {"high": "destructive", "low": "warning", "normal": "success"}

        sparkline_data = [
            {"date": r["result_date"], "value": r["value"]}
            for r in reversed(readings)
        ]

        with Column(gap=4, css_class="p-6 items-center") as view:
            Heading(parameter.upper(), level=3)
            Ring(value=score, max=100)
            if latest:
                Metric(label="Current Value", value=f"{latest['value']} {match['unit']}")
            Badge(status.upper(), variant=status_variant.get(status, "default"))
            Muted(f"Normal range: {ref_min} – {ref_max} {match['unit']}")
            if len(readings) > 1:
                Heading("Trend", level=5)
                Sparkline(data=sparkline_data, data_key="value")

        return PrefabApp(view=view)
