from typing import Literal
from agent.tools import make_agent_tools, PHASE1_ORGANS
from agent.prompts import build_system_prompt, build_user_prompt
from agent.loop import run_agent_loop
from agent.assembler import assemble_dashboard
from core.scorer import score_organ
from core.organs import OrganMapper
from db.store import Store


def _build_organ_summaries_for_agent(store: Store, mapper: OrganMapper, patient_id: str) -> list[dict]:
    summaries = []
    for organ in PHASE1_ORGANS:
        params = store.get_parameters_for_organ(patient_id, organ)
        if not params:
            continue
        critical = {p["name"].upper() for p in params if mapper.is_critical(p["name"])}
        score = score_organ(params, critical)
        flagged = sum(1 for p in params if p["readings"] and p["readings"][0]["status"] != "normal")
        summaries.append({
            "organ": organ,
            "score": score,
            "flagged_count": flagged,
            "parameter_count": len(params),
            "emoji": mapper.get_organ_emoji(organ),
        })
    return summaries


def register(mcp, get_store, get_mapper, get_client):
    @mcp.tool(app=True)
    def run_health_agent(
        patient_id: str,
        context: str = "",
        style: Literal["progressive", "batch"] = "progressive",
        report_ids: list[str] | None = None,
    ):
        """Run the autonomous health analysis agent to build a personalized dashboard."""
        store = get_store()
        mapper = get_mapper()
        client = get_client()

        organ_summaries = _build_organ_summaries_for_agent(store, mapper, patient_id)
        if not organ_summaries:
            from prefab_ui import PrefabApp
            from prefab_ui.components import Column, Text
            with Column() as view:
                Text(f"No data found for patient {patient_id}. Use upload_report first.")
            return PrefabApp(view=view)

        system_prompt = build_system_prompt(style)
        user_prompt = build_user_prompt(organ_summaries, context)
        agent_tools = make_agent_tools(store, mapper, client, patient_id)

        ui_blocks = run_agent_loop(client, system_prompt, user_prompt, agent_tools)

        return assemble_dashboard(ui_blocks, patient_id, store, mapper)
