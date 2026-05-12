import json

_cache: dict[tuple, dict] = {}

_REC_SYSTEM = "You are a health optimization assistant. Return ONLY valid JSON, no explanation."

_REC_PROMPT = """A patient's {organ} lab results show these flagged parameters:
{flagged}

Generate evidence-based recommendations in exactly this JSON format:
{{
  "diet": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "exercise": [{{"title": str, "description": str, "priority": "high|medium|low"}}],
  "supplements": [{{"title": str, "description": str, "priority": "high|medium|low"}}]
}}
Max 3 items per category. Be specific and practical.
Note: These are general wellness suggestions, not medical advice."""


def fetch_recommendations(client, organ: str, flagged_params: list[dict], patient_id: str = "") -> dict:
    cache_key = (patient_id, organ, tuple(sorted(p["name"] for p in flagged_params)))
    if cache_key in _cache:
        return _cache[cache_key]

    if not flagged_params:
        return {"diet": [], "exercise": [], "supplements": []}

    flagged_text = "\n".join(
        f"- {p['name']}: {p['readings'][0]['value']} {p['unit']} "
        f"(normal: {p['ref_min']}–{p['ref_max']})"
        for p in flagged_params if p.get("readings")
    )
    raw = client.complete(
        system=_REC_SYSTEM,
        user=_REC_PROMPT.format(organ=organ, flagged=flagged_text),
    )
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON for recommendations: {e}") from e
    _cache[cache_key] = result
    return result


def register(mcp, get_store, get_client):
    @mcp.tool()
    def get_recommendations(patient_id: str, organ: str) -> str:
        """Get AI-generated diet, exercise, and supplement recommendations for an organ."""
        store = get_store()
        client = get_client()
        params = store.get_parameters_for_organ(patient_id, organ)
        flagged = [p for p in params if p["readings"] and p["readings"][0]["status"] != "normal"]
        recs = fetch_recommendations(client, organ, flagged, patient_id)
        return json.dumps(recs, indent=2)
