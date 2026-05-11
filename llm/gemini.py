import json
from dataclasses import dataclass
from typing import Any, Callable
from google import genai
from google.genai import types


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict        # JSON Schema object
    fn: Callable[..., Any]


@dataclass
class ToolCall:
    name: str
    input: dict
    output: Any


class GeminiClient:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash", stop_tool: str = "finish_dashboard"):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._stop_tool = stop_tool

    def complete(self, system: str, user: str) -> str:
        response = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return response.text

    def tool_loop(
        self,
        system: str,
        user: str,
        agent_tools: list[AgentTool],
    ) -> list[ToolCall]:
        tool_map = {t.name: t for t in agent_tools}
        gemini_tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=types.Schema(**t.parameters),
                )
                for t in agent_tools
            ]
        )
        contents = [types.Content(role="user", parts=[types.Part(text=user)])]
        results: list[ToolCall] = []

        while True:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[gemini_tool],
                ),
            )
            candidate = response.candidates[0]
            contents.append(candidate.content)

            fn_calls = [p for p in candidate.content.parts if p.function_call]
            if not fn_calls:
                break

            function_responses = []
            for part in fn_calls:
                fc = part.function_call
                tool = tool_map.get(fc.name)
                if tool is None:
                    output = {"error": f"Unknown tool: {fc.name}"}
                else:
                    args = dict(fc.args)
                    try:
                        output = tool.fn(**args)
                    except Exception as e:
                        output = {"error": str(e)}

                call = ToolCall(name=fc.name, input=dict(fc.args), output=output)
                results.append(call)

                if fc.name == self._stop_tool:
                    return results

                function_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": json.dumps(output) if not isinstance(output, str) else output},
                        )
                    )
                )

            contents.append(
                types.Content(role="user", parts=function_responses)
            )

        return results
