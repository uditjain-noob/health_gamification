from pydantic import BaseModel
from core.scorer import score_parameter, get_difficulty
from core.organs import OrganMapper
from db.store import Store

_TREND_ARROW = {"improving": "↑", "declining": "↓", "stable": "→"}
_TREND_VARIANT = {"improving": "success", "declining": "destructive", "stable": "default"}


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


def register(mcp, get_store, get_mapper):
    @mcp.tool(app=True)
    def show_bar_comparison(input: ShowBarComparisonInput):
        """
        Show a bar chart comparing all parameters for an organ, ranked by deviation from normal.

        Renders a horizontal bar chart with each parameter's current value, color-coded by status
        (red = high, yellow = low, green = normal), sorted so the most out-of-range appear first.
        Use this to visually compare multiple parameters within one organ at a glance.
        Pair with show_organ_panel for full details or show_gauge_chart to zoom into one parameter.

        Parameters:
        - patient_id: the patient's ID
        - organ: organ name (e.g. "liver", "blood") — case-insensitive
        """
        patient_id = input.patient_id
        organ = input.organ
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
    def show_gauge_chart(input: ShowGaugeChartInput):
        """
        Show a circular gauge (Ring) for a single lab parameter with its trend sparkline.

        Renders: score ring (0–100), current value with unit, normal/high/low status badge,
        reference range, and a sparkline of historical values if multiple readings exist.
        Use this when a user asks about one specific parameter ("show me my LDL", "what's my HbA1c trend?").
        Parameter matching is case-insensitive and uses the exact parameter name from the lab report.
        Call get_organ_parameters to discover valid parameter names for a patient.

        Parameters:
        - patient_id: the patient's ID
        - parameter: exact parameter name (e.g. "LDL CHOLESTEROL - DIRECT", "HEMOGLOBIN")
        """
        patient_id = input.patient_id
        parameter = input.parameter
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
                Sparkline(data=[p["value"] for p in sparkline_data])

        return PrefabApp(view=view)

    @mcp.tool(app=True)
    def show_trend_chart(input: ShowTrendChartInput):
        """
        Show score-over-time sparkline cards for parameters that have multiple readings.

        Renders a grid of cards — one per parameter with ≥2 readings — each showing a sparkline
        of score history (0–100), trend direction arrow (↑ improving / → stable / ↓ declining),
        and latest value badge. Groups cards by organ with section headers.
        Only shows parameters with enough history to compute a trend; omits single-reading parameters.
        Use this when a user asks "am I getting better?", "show my trends", or after uploading a second report.

        Parameters:
        - patient_id: the patient's ID
        - organs: optional list of organ names to filter (e.g. ["liver", "heart"]); omit for all organs
        - lookback: number of past readings to include per parameter (default 5)
        """
        patient_id = input.patient_id
        organs = input.organs
        lookback = input.lookback
        from prefab_ui import PrefabApp
        from prefab_ui.components import (
            Column, Row, Grid, Card, CardContent, Heading, Badge, Muted, Separator
        )
        from prefab_ui.components.charts import Sparkline

        store = get_store()
        mapper = get_mapper()
        trends = store.get_parameter_trends(patient_id, organs=organs, lookback=lookback)
        trends = [t for t in trends if len(t["series"]) >= 2]

        if not trends:
            with Column(css_class="p-6") as view:
                Muted("No trend data available — upload multiple reports to see trends.")
            return PrefabApp(view=view)

        by_organ: dict[str, list] = {}
        for t in trends:
            by_organ.setdefault(t["organ"], []).append(t)

        status_variant = {"high": "destructive", "low": "warning", "normal": "success"}

        with Column(gap=6, css_class="p-6") as view:
            label = f"Last {lookback} readings" if lookback else "All readings"
            Heading(f"Parameter Trends — {label}", level=2)

            for organ, params in by_organ.items():
                emoji = mapper.get_organ_emoji(organ)
                Heading(f"{emoji} {organ.title()}", level=3)
                with Grid(columns=3, gap=3):
                    for t in params:
                        arrow = _TREND_ARROW.get(t["direction"] or "stable", "→")
                        trend_variant = _TREND_VARIANT.get(t["direction"] or "stable", "default")
                        with Card():
                            with CardContent(css_class="p-3"):
                                with Row(justify="between", align="center"):
                                    Muted(t["name"], css_class="text-xs font-medium truncate")
                                    Badge(arrow, variant=trend_variant)
                                if t["latest_value"] is not None:
                                    Badge(
                                        f"{t['latest_value']} {t['unit']}",
                                        variant=status_variant.get(t["latest_status"] or "normal", "default"),
                                        css_class="mt-1",
                                    )
                                Sparkline(
                                    data=[p["score"] for p in t["series"]],
                                    css_class="mt-2 h-12",
                                )
                Separator(css_class="my-2")

        return PrefabApp(view=view)
