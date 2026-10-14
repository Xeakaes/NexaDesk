from ui.settings import KNOWN_TOOLS, merge_permissions


def test_merge_preserves_unknown_tool_entries():
    existing = {"*": "ask", "mouse": "deny", "screenshot": "allow"}
    per_tool = {"screenshot": "ask", "list_windows": "ask"}
    merged = merge_permissions(existing, "ask", per_tool)
    assert merged["mouse"] == "deny"       # not shown in UI — kept
    # B65: rows equal to the default are dropped so check() falls through
    # to "*"; the default actually takes effect for those tools.
    assert "screenshot" not in merged
    assert "list_windows" not in merged
    assert merged["*"] == "ask"


def test_merge_keeps_rows_differing_from_default():
    existing = {"*": "deny"}
    per_tool = {"screenshot": "allow", "mouse": "deny"}
    merged = merge_permissions(existing, "deny", per_tool)
    assert merged["screenshot"] == "allow"  # explicit override kept
    assert "mouse" not in merged            # equals default — dropped


def test_known_tools_match_registry_names():
    assert set(KNOWN_TOOLS) == {
        "screenshot", "ocr_screen", "mouse", "keyboard", "list_windows", "focus_window",
    }
