import json
from pydantic import BaseModel

from apps.rag_retriever import load_store, retrieve as rag_retrieve

load_store()

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

_RAG_SYSTEM = (
    "You are a health optimization assistant. "
    "Use the provided context as grounding. Return ONLY valid JSON, no explanation."
)

_RAG_PROMPT = """Context from medical literature:
{context}

---
Based on the above context, generate evidence-based recommendations for a patient with:
Organ: {organ}
Concern: {query}

Return exactly this JSON format:
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


def fetch_rag_recommendations(client, organ: str, query: str, context_chunks: list[str]) -> dict:
    """Call Gemini with RAG context to generate grounded recommendations.

    Returns empty lists for all categories if context_chunks is empty.
    Raises ValueError if LLM returns invalid JSON.
    """
    if not context_chunks:
        return {"diet": [], "exercise": [], "supplements": []}

    context = "\n\n---\n\n".join(context_chunks)
    raw = client.complete(
        system=_RAG_SYSTEM,
        user=_RAG_PROMPT.format(context=context, organ=organ, query=query),
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON for RAG recommendations: {e}") from e


class GetRecommendationsInput(BaseModel):
    patient_id: str
    organ: str


def register(mcp, get_store, get_client):
    @mcp.tool()
    def get_recommendations(input: GetRecommendationsInput) -> str:
        """
        Get AI-generated, evidence-based recommendations for improving an organ's flagged parameters.

        Returns a JSON string with three categories — diet, exercise, supplements — each containing
        up to 3 actionable items with title, description, and priority (high/medium/low).
        Only generates recommendations for out-of-range parameters; returns empty lists if all are normal.
        Results are cached per (patient_id, organ) so repeat calls are free.
        Use this when a user asks "what should I do about my liver?" or "how can I improve my cholesterol?".
        For a visual version with the same content embedded in a panel, use show_organ_panel instead.

        Parameters:
        - patient_id: the patient's ID
        - organ: organ name (e.g. "liver", "heart") — case-insensitive
        """
        patient_id = input.patient_id
        organ = input.organ
        store = get_store()
        client = get_client()
        params = store.get_parameters_for_organ(patient_id, organ)
        flagged = [p for p in params if p["readings"] and p["readings"][0]["status"] != "normal"]
        recs = fetch_recommendations(client, organ, flagged, patient_id)
        return json.dumps(recs, indent=2)

    @mcp.tool()
    def get_rag_recommendations(query: str, organ: str, category: str = "all") -> str:
        """
        Get RAG-grounded diet/exercise/supplement recommendations backed by medical literature.

        Construct `query` from the patient's flagged parameters and condition, e.g.:
        "elevated SGPT SGOT fatty liver diet exercise reduce enzymes"

        Parameters:
        - query: free-text description of the patient's concern — the agent composes this
        - organ: organ system, e.g. "liver", "heart", "blood", "metabolic", "kidney", "vitamins"
        - category: narrow results to "diet", "exercise", or "supplement"; default "all"

        Returns JSON: {"diet": [...], "exercise": [...], "supplements": [...]}
        Each item: {"title": str, "description": str, "priority": "high|medium|low"}
        Max 3 items per category.
        """
        client = get_client()
        context_chunks = rag_retrieve(query, organ, category, top_k=5)
        recs = fetch_rag_recommendations(client, organ, query, context_chunks)
        return json.dumps(recs, indent=2)
