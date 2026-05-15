import time
from unittest.mock import MagicMock
from llm.gemini import _execute_tool_calls, AgentTool, ToolCall


def _make_part(name: str, args: dict):
    part = MagicMock()
    part.function_call.name = name
    part.function_call.args = args
    return part


def test_parallel_execution_faster_than_sequential():
    SLEEP = 0.15

    def slow_a(x):
        time.sleep(SLEEP)
        return {"a": x}

    def slow_b(x):
        time.sleep(SLEEP)
        return {"b": x}

    tool_map = {
        "tool_a": AgentTool(name="tool_a", description="", parameters={}, fn=slow_a),
        "tool_b": AgentTool(name="tool_b", description="", parameters={}, fn=slow_b),
    }
    parts = [_make_part("tool_a", {"x": 1}), _make_part("tool_b", {"x": 2})]

    start = time.monotonic()
    results = _execute_tool_calls(parts, tool_map)
    elapsed = time.monotonic() - start

    assert len(results) == 2
    # Parallel: should finish in ~SLEEP, not 2*SLEEP
    assert elapsed < SLEEP * 1.8
    result_names = {r.name for r in results}
    assert result_names == {"tool_a", "tool_b"}


def test_tool_error_does_not_kill_other_tools():
    def failing_tool(x):
        raise ValueError("oops")

    def good_tool(x):
        return {"value": x}

    tool_map = {
        "failing": AgentTool(name="failing", description="", parameters={}, fn=failing_tool),
        "good": AgentTool(name="good", description="", parameters={}, fn=good_tool),
    }
    parts = [_make_part("failing", {"x": 1}), _make_part("good", {"x": 42})]
    results = _execute_tool_calls(parts, tool_map)

    assert len(results) == 2
    failing = next(r for r in results if r.name == "failing")
    good = next(r for r in results if r.name == "good")
    assert "error" in failing.output
    assert good.output == {"value": 42}


def test_unknown_tool_returns_error_dict():
    parts = [_make_part("nonexistent", {"x": 1})]
    results = _execute_tool_calls(parts, tool_map={})

    assert len(results) == 1
    assert results[0].output == {"error": "Unknown tool: nonexistent"}


def test_single_tool_call_works():
    tool_map = {
        "echo": AgentTool(name="echo", description="", parameters={}, fn=lambda msg: {"echo": msg}),
    }
    results = _execute_tool_calls([_make_part("echo", {"msg": "hi"})], tool_map)
    assert results[0].output == {"echo": "hi"}


def test_stop_tool_in_batch_siblings_all_execute():
    ran = []

    def stop_fn():
        ran.append("stop")
        return {"status": "done"}

    def sibling_fn():
        ran.append("sibling")
        return {"ok": True}

    tool_map = {
        "finish": AgentTool(name="finish", description="", parameters={}, fn=stop_fn),
        "sibling": AgentTool(name="sibling", description="", parameters={}, fn=sibling_fn),
    }
    results = _execute_tool_calls(
        [_make_part("sibling", {}), _make_part("finish", {})], tool_map
    )
    assert set(ran) == {"stop", "sibling"}
    assert len(results) == 2
