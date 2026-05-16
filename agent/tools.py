from llm.gemini import AgentTool
from core.organs import OrganMapper
from db.store import Store
from agent.mcp_tools import (
    GetParamsByOrganInput,
    GetParamsByOrganAgentInput,
    GetRecommendationsForCaseInput,
    GetRecommendationsForCaseAgentInput,
    BuildOrganUISectionInput,
    PrioritizeOrgansInput,
    FinishDashboardInput,
    get_params_by_organ_fn,
    get_recommendations_for_case_fn,
    build_organ_ui_section_fn,
    prioritize_organs_fn,
    finish_dashboard_fn,
)


def make_agent_tools(store: Store, mapper: OrganMapper, client, patient_id: str) -> list[AgentTool]:
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
            name="get_recommendations_for_case",
            description="Get goal-aware AI recommendations for flagged parameters in an organ.",
            parameters=GetRecommendationsForCaseAgentInput.model_json_schema(),
            fn=lambda **kwargs: get_recommendations_for_case_fn(
                GetRecommendationsForCaseInput(patient_id=patient_id, **kwargs),
                store, client,
            ),
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
