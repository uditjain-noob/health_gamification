from llm.gemini import GeminiClient, AgentTool, ToolCall


def run_agent_loop(
    client: GeminiClient,
    system: str,
    user: str,
    agent_tools: list[AgentTool],
) -> list[dict]:
    """Runs the Gemini tool-use loop. Returns list of UIBlock dicts from build_organ_ui_section calls."""
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
    return ui_blocks
