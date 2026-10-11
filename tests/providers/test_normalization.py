import json
from core.providers.base import ChatMessage, ToolCall
from core.providers.ollama import serialize_messages as so, to_provider_tools as tpo
from core.providers.openai_compatible import serialize_messages as sa, to_provider_tools as tpa

HISTORY = [
    ChatMessage(role="user", content="ekran görüntüsü al"),
    ChatMessage(role="assistant", content=None,
                tool_calls=[ToolCall(id="c1", name="screenshot", arguments={})]),
    ChatMessage(role="tool", content='{"ok": true, "data": {"path": "x.png"}}',
                tool_call_id="c1", name="screenshot"),
]

def test_internal_schema_to_provider_tools():
    schemas = [{"name": "screenshot", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
    o, a = tpo(schemas), tpa(schemas)
    assert o[0]["function"]["name"] == "screenshot"
    assert a[0]["type"] == "function" and a[0]["function"]["name"] == "screenshot"

def test_ollama_replays_assistant_tool_calls_history():
    wire = so(HISTORY)
    assert wire[1]["role"] == "assistant"
    assert wire[1]["tool_calls"][0]["function"]["name"] == "screenshot"
    assert wire[1]["tool_calls"][0]["function"]["arguments"] == {}
    assert wire[2]["role"] == "tool" and wire[2]["tool_call_id"] == "c1"

def test_openai_replays_assistant_tool_calls_history():
    wire = sa(HISTORY)
    assert wire[1]["role"] == "assistant"
    tc = wire[1]["tool_calls"][0]
    assert tc["id"] == "c1" and tc["type"] == "function"
    assert json.loads(tc["function"]["arguments"]) == {}
    assert wire[2]["role"] == "tool" and wire[2]["tool_call_id"] == "c1"
