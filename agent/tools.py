from llm.gemini import AgentTool
from core.organs import OrganMapper
from db.store import Store
from agent.mcp_tools import (
    GetParamsByOrganInput,
    GetParamsByOrganAgentInput,
    BuildOrganUISectionInput,
    PrioritizeOrgansInput,
    FinishDashboardInput,
    get_params_by_organ_fn,
    build_organ_ui_section_fn,
    prioritize_organs_fn,
    finish_dashboard_fn,
)
from apps.recommendations import GetRagRecommendationsInput, fetch_rag_recommendations
from apps.rag_retriever import retrieve as rag_retrieve


def make_agent_tools(store: Store, mapper: OrganMapper, client, patient_id: str) -> list[AgentTool]:

    def rag_recs_fn(**kwargs):
        inp = GetRagRecommendationsInput(**kwargs)
        chunks = rag_retrieve(inp.query, inp.organ, inp.category, top_k=5)
        return fetch_rag_recommendations(client, inp.organ, inp.query, chunks)

    return [
        AgentTool(
            name="prioritize_organs",
            description="Decide which organ systems to investigate first based on severity and user context.",
            parameters=PrioritizeOrgansInput.model_json_schema(),
            fn=lambda **kwargs: prioritize_organs_fn(PrioritizeOrgansInput(**kwargs)),
        ),
        AgentTool(
            name="get_params_by_organ",
            description="Fetch all parameter values, reference ranges, and readings for an organ system.",
            parameters=GetParamsByOrganAgentInput.model_json_schema(),
            fn=lambda **kwargs: get_params_by_organ_fn(
                GetParamsByOrganInput(patient_id=patient_id, **kwargs),
                store, mapper,
            ),
        ),
        AgentTool(
            name="get_rag_recommendations",
            description="Get RAG-grounded diet/exercise/supplement recommendations backed by medical literature. Compose query from the organ's flagged parameter names and patient context.",
            parameters=GetRagRecommendationsInput.model_json_schema(),
            fn=rag_recs_fn,
        ),
        AgentTool(
            name="build_organ_ui_section",
            description="Build the Prefab UI section card for one organ using fetched data and recommendations.",
            parameters=BuildOrganUISectionInput.model_json_schema(),
            fn=lambda **kwargs: build_organ_ui_section_fn(
                BuildOrganUISectionInput(**kwargs), mapper
            ),
        ),
        AgentTool(
            name="finish_dashboard",
            description="Signal that all organ sections are complete. Call this last.",
            parameters=FinishDashboardInput.model_json_schema(),
            fn=lambda **kwargs: finish_dashboard_fn(FinishDashboardInput(**kwargs)),
        ),
    ]
