import pytest
from core.tools.base import Tool, ToolResult
from core.tools.registry import PermissionPolicy, PermissionLevel, ToolRegistry

class Dummy(Tool):
    name = "dummy"; description = "d"; input_schema = {"type": "object"}
    def __init__(self): self.calls = []
    def execute(self, arguments, cancel):
        self.calls.append(arguments); return ToolResult(ok=True)

def test_policy_wildcard_default_ask():
    assert PermissionPolicy({}).check("anything") is PermissionLevel.ASK

def test_policy_exact_beats_wildcard():
    p = PermissionPolicy({"*": "ask", "screenshot": "allow"})
    assert p.check("screenshot") is PermissionLevel.ALLOW
    assert p.check("mouse") is PermissionLevel.ASK

def test_policy_deny():
    p = PermissionPolicy({"*": "deny"})
    assert p.check("x") is PermissionLevel.DENY

def test_register_duplicate_raises():
    r = ToolRegistry(); r.register(Dummy())
    with pytest.raises(ValueError): r.register(Dummy())

def test_schemas_shape():
    r = ToolRegistry(); r.register(Dummy())
    assert r.schemas() == [{"name": "dummy", "description": "d", "input_schema": {"type": "object"}}]

def test_unregister_removes_tool():
    r = ToolRegistry(); r.register(Dummy())
    r.unregister("dummy")
    assert r.get("dummy") is None
    r.unregister("dummy")  # idempotent: save-time toggles unregister first
    assert r.names() == []
