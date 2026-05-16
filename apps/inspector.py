"""
MCP Inspector — live diagnostics for the HealthQuest server.
Shows: DB stats, organ mapping validation, query function results,
and the full tool registry with schemas.
"""
import json
import logging
import traceback
from pydantic import BaseModel
from db.store import Store
from core.organs import OrganMapper
from core.scorer import score_parameter, score_organ, compute_trend

log = logging.getLogger("healthquest.inspector")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class ShowInspectorInput(BaseModel):
    patient_id: str = ""


def register(mcp, get_store, get_mapper):

    @mcp.tool(app=True)
    def show_inspector(input: ShowInspectorInput):
        """Inspect the HealthQuest server: DB stats, organ mapping, query results, tool registry."""
        patient_id = input.patient_id
        log.info("show_inspector called — patient_id=%r", patient_id)

        from prefab_ui import PrefabApp
        from prefab_ui.components import (
            Column, Row, Grid, Card, CardContent, CardHeader, CardTitle,
            Heading, Text, Muted, Badge, Separator, Tabs, Tab,
        )

        try:
            store = get_store()
            log.info("store acquired: %r", store)
            mapper = get_mapper()
            log.info("mapper acquired")
        except Exception:
            log.error("Failed to acquire store/mapper:\n%s", traceback.format_exc())
            raise

        # ── DB stats ──────────
        # ────────────────────────────────────────────────
        try:
            db_stats = _collect_db_stats(store, patient_id)
            log.info("db_stats: summary=%s organs=%d", db_stats["summary"], len(db_stats["organs"]))
        except Exception:
            log.error("_collect_db_stats failed:\n%s", traceback.format_exc())
            raise

        # ── Organ mapping spot-check ──────────────────────────────────────────
        try:
            mapping_checks = _check_organ_mapping(mapper)
            log.info("mapping_checks: %d checks", len(mapping_checks))
        except Exception:
            log.error("_check_organ_mapping failed:\n%s", traceback.format_exc())
            raise

        # ── Query function results (only if patient_id given) ─────────────────
        try:
            query_results = _run_query_checks(store, mapper, patient_id) if patient_id else []
            log.info("query_results: %d checks", len(query_results))
        except Exception:
            log.error("_run_query_checks failed:\n%s", traceback.format_exc())
            raise

        # ── Tool registry ─────────────────────────────────────────────────────
        try:
            tool_registry = _get_tool_registry(mcp)
            log.info("tool_registry: %d tools", len(tool_registry))
        except Exception:
            log.error("_get_tool_registry failed:\n%s", traceback.format_exc())
            raise

        log.info("Building PrefabApp view...")
        with Column(gap=6, css_class="p-6") as view:
            Heading("HealthQuest Inspector", level=2)
            Muted("Live diagnostics — server health, DB state, and query validation")
            Separator()

            with Tabs():
                # ── Tab 1: DB Stats ──────────────────────────────────────────
                with Tab(title="DB Stats"):
                    with Grid(columns=3, gap=4, css_class="mt-4"):
                        for stat in db_stats["summary"]:
                            with Card():
                                with CardContent(css_class="p-4"):
                                    Heading(str(stat["value"]), level=3)
                                    Muted(stat["label"])

                    if db_stats["organs"]:
                        Heading("Parameters by Organ", level=4, css_class="mt-6")
                        with Grid(columns=4, gap=3):
                            for row in db_stats["organs"]:
                                with Card():
                                    with CardContent(css_class="p-3"):
                                        emoji = mapper.get_organ_emoji(row["organ"])
                                        with Row(justify="between"):
                                            Text(f"{emoji} {row['organ'].title()}", css_class="font-semibold")
                                            Badge(str(row["params"]), variant="outline")
                                        Muted(f"{row['readings']} readings")
                                        if row["trends"] > 0:
                                            Muted(f"{row['trends']} with trend data")

                    if not patient_id:
                        Muted("Enter a patient_id to see per-organ details", css_class="mt-4")

                # ── Tab 2: Query Checks ───────────────────────────────────────
                with Tab(title="Query Checks"):
                    if not patient_id:
                        with Card(css_class="mt-4"):
                            with CardContent(css_class="p-5"):
                                Text("Pass a patient_id to run live query checks.")
                    else:
                        with Column(gap=4, css_class="mt-4"):
                            for check in query_results:
                                ok = check["status"] == "ok"
                                with Card():
                                    with CardContent(css_class="p-4"):
                                        with Row(justify="between", align="center"):
                                            Text(check["name"], css_class="font-semibold")
                                            Badge("✓ ok" if ok else "✗ fail",
                                                  variant="success" if ok else "destructive")
                                        Muted(check["detail"])

                # ── Tab 3: Organ Mapping ──────────────────────────────────────
                with Tab(title="Organ Mapping"):
                    Heading("Spot-check: real lab names → organs", level=4, css_class="mt-4")
                    with Column(gap=2, css_class="mt-2"):
                        for c in mapping_checks:
                            ok = c["actual"] == c["expected"]
                            with Row(gap=3, align="center", css_class="py-1"):
                                Badge("✓" if ok else "✗",
                                      variant="success" if ok else "destructive")
                                Muted(c["name"], css_class="flex-1 truncate")
                                Text(f"→ {c['actual']}", css_class="font-mono text-sm")
                                if not ok:
                                    Muted(f"(expected {c['expected']})", css_class="text-destructive")

                # ── Tab 4: Tool Registry ──────────────────────────────────────
                with Tab(title="Tools"):
                    with Column(gap=3, css_class="mt-4"):
                        for tool in tool_registry:
                            with Card():
                                with CardContent(css_class="p-4"):
                                    with Row(justify="between", align="center"):
                                        Text(tool["name"], css_class="font-semibold font-mono")
                                        Badge(f"{len(tool['params'])} params", variant="outline")
                                    Muted(tool["description"])
                                    if tool["params"]:
                                        with Row(gap=2, css_class="mt-2 flex-wrap"):
                                            for p in tool["params"]:
                                                Badge(p, variant="secondary")

        log.info("PrefabApp built — returning")
        app = PrefabApp(view=view)
        log.info("PrefabApp type=%s", type(app))
        return app


# ── helpers ────────────────────────────────────────────────────────────────────

def _collect_db_stats(store: Store, patient_id: str) -> dict:
    conn = store._get_conn()

    total_patients = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    total_params = conn.execute("SELECT COUNT(*) FROM parameters").fetchone()[0]
    total_readings = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]

    summary = [
        {"label": "Patients", "value": total_patients},
        {"label": "Parameters", "value": total_params},
        {"label": "Readings", "value": total_readings},
    ]

    organs = []
    if patient_id:
        cur = conn.execute("""
            SELECT p.organ,
                   COUNT(DISTINCT p.id) as params,
                   COUNT(r.id) as readings
            FROM parameters p
            LEFT JOIN readings r ON r.parameter_id = p.id
            WHERE p.patient_id = ?
            GROUP BY p.organ
            ORDER BY params DESC
        """, (patient_id,))
        for row in cur.fetchall():
            organ, params, readings = row
            # Count parameters with >1 reading (have trend data)
            trend_cur = conn.execute("""
                SELECT COUNT(*) FROM (
                    SELECT parameter_id FROM readings
                    WHERE parameter_id IN (
                        SELECT id FROM parameters WHERE patient_id = ? AND organ = ?
                    )
                    GROUP BY parameter_id HAVING COUNT(*) > 1
                )
            """, (patient_id, organ))
            trends = trend_cur.fetchone()[0]
            organs.append({"organ": organ, "params": params, "readings": readings, "trends": trends})

    return {"summary": summary, "organs": organs}


def _check_organ_mapping(mapper: OrganMapper) -> list[dict]:
    checks = [
        ("ALANINE TRANSAMINASE (SGPT)", "liver"),
        ("BILIRUBIN - TOTAL", "liver"),
        ("BILIRUBIN (INDIRECT)", "liver"),
        ("PROTEIN - TOTAL", "liver"),
        ("SERUM ALB/GLOBULIN RATIO", "liver"),
        ("CREATININE - SERUM", "kidney"),
        ("BLOOD UREA NITROGEN (BUN)", "kidney"),
        ("SPECIFIC GRAVITY", "kidney"),
        ("HEMOGLOBIN", "blood"),
        ("LYMPHOCYTE", "blood"),
        ("IMMATURE GRANULOCYTE PERCENTAGE(IG%)", "blood"),
        ("PLATELETCRIT(PCT)", "blood"),
        ("TOTAL CHOLESTEROL", "heart"),
        ("LDL CHOLESTEROL - DIRECT", "heart"),
        ("LDL / HDL RATIO", "heart"),
        ("TRIG / HDL RATIO", "heart"),
        ("TC/ HDL CHOLESTEROL RATIO", "heart"),
        ("TSH - ULTRASENSITIVE", "thyroid"),
        ("HbA1c", "metabolic"),
        ("FASTING BLOOD SUGAR(GLUCOSE)", "metabolic"),
        ("25-OH VITAMIN D (TOTAL)", "bone"),
        ("VITAMIN B-12", "bone"),
        ("CALCIUM", "vitamins"),
    ]
    return [
        {"name": name, "expected": expected, "actual": mapper.get_organ(name)}
        for name, expected in checks
    ]


def _run_query_checks(store: Store, mapper: OrganMapper, patient_id: str) -> list[dict]:
    results = []

    # 1. get_organ_summaries
    try:
        summaries = store.get_organ_summaries(patient_id)
        organs = [s["organ"] for s in summaries]
        results.append({
            "name": "get_organ_summaries",
            "status": "ok" if organs else "fail",
            "detail": f"Found organs: {', '.join(organs) or 'none'}",
        })
    except Exception as e:
        results.append({"name": "get_organ_summaries", "status": "fail", "detail": str(e)})

    # 2. get_parameters_for_organ (first organ found)
    try:
        summaries = store.get_organ_summaries(patient_id)
        if summaries:
            organ = summaries[0]["organ"]
            params = store.get_parameters_for_organ(patient_id, organ)
            results.append({
                "name": f"get_parameters_for_organ({organ})",
                "status": "ok" if params else "fail",
                "detail": f"{len(params)} parameters, "
                          f"{sum(len(p['readings']) for p in params)} total readings",
            })
    except Exception as e:
        results.append({"name": "get_parameters_for_organ", "status": "fail", "detail": str(e)})

    # 3. score_organ
    try:
        if summaries:
            organ = summaries[0]["organ"]
            params = store.get_parameters_for_organ(patient_id, organ)
            critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
            score = score_organ(params, critical)
            results.append({
                "name": f"score_organ({organ})",
                "status": "ok" if 0 <= score <= 100 else "fail",
                "detail": f"Score: {score}/100  critical params: {len(critical)}",
            })
    except Exception as e:
        results.append({"name": "score_organ", "status": "fail", "detail": str(e)})

    # 4. get_parameter_trends
    try:
        trends = store.get_parameter_trends(patient_id, lookback=5)
        with_trend = [t for t in trends if t["direction"] is not None]
        dirs = {}
        for t in with_trend:
            dirs[t["direction"]] = dirs.get(t["direction"], 0) + 1
        results.append({
            "name": "get_parameter_trends",
            "status": "ok",
            "detail": f"{len(trends)} params total, {len(with_trend)} with trend data  "
                      + "  ".join(f"{d}: {n}" for d, n in dirs.items()),
        })
    except Exception as e:
        results.append({"name": "get_parameter_trends", "status": "fail", "detail": str(e)})

    # 5. compute_trend spot-check (liver SGPT if present)
    try:
        liver_params = store.get_parameters_for_organ(patient_id, "liver")
        sgpt = next((p for p in liver_params if "SGPT" in p["name"].upper()), None)
        if sgpt and len(sgpt["readings"]) >= 2:
            direction = compute_trend(sgpt["readings"], sgpt["ref_min"], sgpt["ref_max"])
            results.append({
                "name": "compute_trend (SGPT)",
                "status": "ok" if direction else "fail",
                "detail": f"{len(sgpt['readings'])} readings → direction: {direction}",
            })
        else:
            results.append({
                "name": "compute_trend (SGPT)",
                "status": "ok",
                "detail": "SGPT not found or only 1 reading — skipped",
            })
    except Exception as e:
        results.append({"name": "compute_trend", "status": "fail", "detail": str(e)})

    # 6. XP total
    try:
        xp = store.get_xp_total(patient_id)
        results.append({
            "name": "get_xp_total",
            "status": "ok",
            "detail": f"{xp} XP earned",
        })
    except Exception as e:
        results.append({"name": "get_xp_total", "status": "fail", "detail": str(e)})

    return results


def _get_tool_registry(mcp) -> list[dict]:
    tools = []
    try:
        for tool in mcp._tool_manager._tools.values():
            params = list(tool.parameters.get("properties", {}).keys()) if tool.parameters else []
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "params": params,
            })
    except Exception:
        pass
    return tools
