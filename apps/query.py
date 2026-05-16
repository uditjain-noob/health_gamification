import logging
from pydantic import BaseModel
from db.store import Store
from core.organs import OrganMapper
from core.scorer import score_parameter, score_organ, compute_trend

log = logging.getLogger("healthquest.query")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


class ListOrgansInput(BaseModel):
    patient_id: str

class GetOrganParametersInput(BaseModel):
    patient_id: str
    organ: str

class GetPatientSummaryInput(BaseModel):
    patient_id: str


def register(mcp, get_store, get_mapper):
    @mcp.tool()
    def list_organs(input: ListOrgansInput) -> list[dict]:
        """
        List all organ systems that have lab data for a patient, with scores and parameter counts.

        Returns a list sorted by score ascending (worst first), each entry containing:
        organ name, score (0–100), and parameter_count.
        Use this as the first call when you don't know what data exists for a patient,
        or to identify which organ needs attention before drilling in with get_organ_parameters.
        All organ names returned here are valid inputs for other tools.

        Parameters:
        - patient_id: the patient's ID
        """
        patient_id = input.patient_id
        log.info("list_organs called — patient_id=%r", patient_id)
        store: Store = get_store()
        mapper: OrganMapper = get_mapper()
        summaries = store.get_organ_summaries(patient_id)
        result = []
        for s in summaries:
            organ = s["organ"]
            params = store.get_parameters_for_organ(patient_id, organ)
            critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
            score = score_organ(params, critical)
            result.append({"organ": organ, "score": score, "parameter_count": len(params)})
        log.info("list_organs result: %d organs", len(result))
        result.sort(key=lambda x: x["score"])
        return result

    @mcp.tool()
    def get_organ_parameters(input: GetOrganParametersInput) -> dict:
        """
        Fetch all parameters for one organ as structured JSON — no charts, pure data.

        Returns organ score, flagged_count, and a parameters list where each entry contains:
        name, unit, ref_min, ref_max, score (0–100), status (normal/high/low),
        trend (improving/stable/declining/null), is_critical, and a readings list of
        {date, value} objects ordered newest-first.
        Trend is null if only one reading exists. is_critical flags parameters with higher clinical weight.

        Use this when you need to reason over data programmatically — e.g. to decide which parameters
        to highlight, to pick the worst-scoring metric, or to feed into a recommendation prompt.
        For a visual equivalent use show_organ_panel; for all organs at once use get_patient_summary.
        Organ name is case-insensitive. Call list_organs first to see valid organ names.

        Parameters:
        - patient_id: the patient's ID
        - organ: organ name (e.g. "liver", "Heart", "blood") — case-insensitive
        """
        patient_id = input.patient_id
        organ = input.organ
        organ_key = organ.strip().lower()
        log.info("get_organ_parameters called — patient_id=%r organ=%r (normalized: %r)", patient_id, organ, organ_key)
        store: Store = get_store()
        mapper: OrganMapper = get_mapper()
        params = store.get_parameters_for_organ(patient_id, organ_key)
        log.info("get_parameters_for_organ returned %d params", len(params))
        if not params:
            log.warning("No params found — check patient_id and organ name. Available organs: call list_organs first.")
            return {"organ": organ_key, "patient_id": patient_id, "parameters": [], "score": None}

        out_params = []
        for p in params:
            readings = p.get("readings", [])
            latest = readings[0] if readings else None
            score = None
            status = None
            trend = None
            if latest is not None:
                score = score_parameter(latest["value"], p["ref_min"], p["ref_max"])
                if p["ref_min"] <= latest["value"] <= p["ref_max"]:
                    status = "normal"
                elif latest["value"] > p["ref_max"]:
                    status = "high"
                else:
                    status = "low"
                trend = compute_trend(readings, p["ref_min"], p["ref_max"])

            out_params.append({
                "name": p["name"],
                "unit": p["unit"],
                "ref_min": p["ref_min"],
                "ref_max": p["ref_max"],
                "score": score,
                "status": status,
                "trend": trend,
                "is_critical": mapper.is_critical(p["name"]),
                "readings": [
                    {"date": r["result_date"], "value": r["value"]}
                    for r in readings
                ],
            })

        critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
        organ_score = score_organ(params, critical)
        flagged = [p for p in out_params if p["status"] != "normal"]
        log.info("get_organ_parameters done — organ=%r score=%d flagged=%d/%d", organ_key, organ_score, len(flagged), len(out_params))

        return {
            "organ": organ_key,
            "patient_id": patient_id,
            "score": organ_score,
            "parameter_count": len(out_params),
            "flagged_count": len(flagged),
            "parameters": out_params,
        }

    @mcp.tool()
    def get_patient_summary(input: GetPatientSummaryInput) -> dict:
        """
        Fetch a full health summary across all organ systems for a patient — no charts, pure JSON.

        Returns overall_score (average across organs), organ_count, total_flagged_parameters,
        and an organs list sorted by score ascending (worst first). Each organ entry contains
        its score and a flagged list of out-of-range parameters with value, unit, status, and is_critical.

        Use this as a single-call snapshot of the patient's entire health state — ideal for deciding
        which organs to focus on, generating a narrative summary, or building a custom view.
        For a visual overview use show_health_dashboard; for one organ's full detail use get_organ_parameters.

        Parameters:
        - patient_id: the patient's ID
        """
        patient_id = input.patient_id
        log.info("get_patient_summary called — patient_id=%r", patient_id)
        store: Store = get_store()
        mapper: OrganMapper = get_mapper()
        summaries = store.get_organ_summaries(patient_id)
        log.info("get_organ_summaries returned %d organs", len(summaries))

        organs_out = []
        total_flagged = 0
        for s in summaries:
            organ = s["organ"]
            params = store.get_parameters_for_organ(patient_id, organ)
            critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
            organ_score = score_organ(params, critical)

            flagged = []
            for p in params:
                readings = p.get("readings", [])
                if not readings:
                    continue
                v = readings[0]["value"]
                if not (p["ref_min"] <= v <= p["ref_max"]):
                    status = "high" if v > p["ref_max"] else "low"
                    flagged.append({
                        "name": p["name"],
                        "value": v,
                        "unit": p["unit"],
                        "status": status,
                        "is_critical": mapper.is_critical(p["name"]),
                    })

            total_flagged += len(flagged)
            organs_out.append({
                "organ": organ,
                "score": organ_score,
                "flagged": flagged,
            })

        organs_out.sort(key=lambda x: x["score"])
        avg_score = round(sum(o["score"] for o in organs_out) / len(organs_out)) if organs_out else 0
        log.info("get_patient_summary done — %d organs avg_score=%d total_flagged=%d", len(organs_out), avg_score, total_flagged)

        return {
            "patient_id": patient_id,
            "overall_score": avg_score,
            "organ_count": len(organs_out),
            "total_flagged_parameters": total_flagged,
            "organs": organs_out,
        }
