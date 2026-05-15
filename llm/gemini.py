import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable
from google import genai
from google.genai import types

log = logging.getLogger("healthquest.gemini")


def _schema_from_dict(d: dict) -> "types.Schema":
    """Recursively convert a raw JSON Schema dict to a types.Schema object."""
    kwargs: dict[str, Any] = {}
    if "type" in d:
        kwargs["type"] = d["type"]
    if "description" in d:
        kwargs["description"] = d["description"]
    if "enum" in d:
        kwargs["enum"] = d["enum"]
    if "properties" in d:
        kwargs["properties"] = {k: _schema_from_dict(v) for k, v in d["properties"].items()}
    if "required" in d:
        kwargs["required"] = d["required"]
    if "items" in d:
        kwargs["items"] = _schema_from_dict(d["items"])
    return types.Schema(**kwargs)


def _to_json_safe(obj: Any) -> Any:
    """Recursively strip non-JSON-serializable values (e.g. Prefab UI components)."""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(i) for i in obj]
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return f"<{type(obj).__name__}>"


def _execute_tool_calls(fn_calls: list, tool_map: dict) -> list["ToolCall"]:
    """Execute all fn_calls in parallel. Returns ToolCall results in fn_calls order."""
    def dispatch(part) -> "ToolCall":
        fc = part.function_call
        tool = tool_map.get(fc.name)
        args = dict(fc.args)
        if tool is None:
            output = {"error": f"Unknown tool: {fc.name}"}
        else:
            try:
                output = tool.fn(**args)
            except Exception as e:
                output = {"error": str(e)}
                log.error("[agent] tool %s raised: %s", fc.name, e)
        log.info("[agent] ← tool_result: %s → %s", fc.name, json.dumps(_to_json_safe(output))[:200])
        return ToolCall(name=fc.name, input=args, output=output)

    with ThreadPoolExecutor() as pool:
        return list(pool.map(dispatch, fn_calls))


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
                    parameters=_schema_from_dict(t.parameters),
                )
                for t in agent_tools
            ]
        )
        contents = [types.Content(role="user", parts=[types.Part(text=user)])]
        results: list[ToolCall] = []

        turn = 0
        while True:
            turn += 1
            log.info("[agent turn %d] calling Gemini (%s)…", turn, self._model)
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    tools=[gemini_tool],
                ),
            )
            candidate = response.candidates[0]

            if candidate.content is None or not candidate.content.parts:
                log.warning(
                    "[agent turn %d] empty content — finish_reason=%s — stopping loop",
                    turn, getattr(candidate, "finish_reason", "unknown"),
                )
                break

            contents.append(candidate.content)

            fn_calls = [p for p in candidate.content.parts if p.function_call]
            if not fn_calls:
                text_parts = [p.text for p in candidate.content.parts if getattr(p, "text", None)]
                log.info("[agent turn %d] no tool calls — model finished. text=%r", turn, " ".join(text_parts)[:200])
                break

            for part in fn_calls:
                fc = part.function_call
                log.info("[agent] → tool_call: %s(%s)", fc.name,
                         ", ".join(f"{k}={repr(v)[:60]}" for k, v in dict(fc.args).items()))

            call_results = _execute_tool_calls(fn_calls, tool_map)
            results.extend(call_results)

            # Check if stop tool was called in this batch
            stop_result = next((c for c in call_results if c.name == self._stop_tool), None)
            if stop_result:
                log.info("[agent] stop tool called — loop complete after %d turns", turn)
                return results

            function_responses = [
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name,
                        response={"result": json.dumps(_to_json_safe(call.output))},
                    )
                )
                for call in call_results
            ]

            contents.append(types.Content(role="user", parts=function_responses))

        return results
