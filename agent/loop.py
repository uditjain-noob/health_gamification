from llm.gemini import GeminiClient, AgentTool, ToolCall


def run_agent_loop(
    client: GeminiClient,
    system: str,
    user: str,
    agent_tools: list[AgentTool],
) -> tuple[list[dict], str]:
    """Returns (ui_blocks, overall_summary)."""
    tool_calls: list[ToolCall] = client.tool_loop(
        system=system,
        user=user,
        agent_tools=agent_tools,
    )
    ui_blocks = [
        call.output
        for call in tool_calls
        if call.name == "build_organ_ui_section" and isinstance(call.output, dict)
    ]
    finish_call = next(
        (call for call in tool_calls if call.name == "finish_dashboard"), None
    )
    overall_summary = ""
    if finish_call and isinstance(finish_call.output, dict):
        overall_summary = finish_call.output.get("summary", "")
    return ui_blocks, overall_summary
