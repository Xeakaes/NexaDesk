"""Docs must make accurate privacy claims (B16).

The landing page used absolute claims ("nothing phones home", "keys never
leave your disk") that the app's own behavior contradicts: an optional
startup update check talks to api.github.com, and API keys are necessarily
sent to the configured model provider.
"""

from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "docs" / "index.html"


def _text() -> str:
    return DOC.read_text(encoding="utf-8").lower()


def test_docs_do_not_claim_nothing_phones_home():
    assert "nothing phones home" not in _text()


def test_docs_do_not_claim_keys_never_leave_disk():
    assert "never leave your disk" not in _text()
    assert "never leave your machine" not in _text()
    assert "entirely on your machine" not in _text()


def test_docs_disclose_update_check():
    text = _text()
    assert "update check" in text
    assert "turn it off" in text or "disable" in text or "turn off" in text


def test_docs_disclose_keys_go_to_provider():
    text = _text()
    assert "provider you configured" in text


def test_readme_tr_port_wording():
    # B77: "boşta değilse" (if the port is busy) inverted the real condition.
    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "boşta değilse" not in text
    assert "boşsa" in text


def test_landing_security_claim_matches_default_policy():
    # B78: the site claimed unlisted tools are "denied by default"; the
    # actual wildcard default is "ask".
    text = DOC.read_text(encoding="utf-8").lower()
    assert "denied by default" not in text
    assert "default to ask" in text


def test_config_template_has_no_dead_keys():
    # B80: language/theme live in ui.json (UiPrefs), not settings.json —
    # the template still advertised both as settings keys.
    import json

    tpl = Path(__file__).resolve().parents[1] / "config_template" / "settings.json"
    data = json.loads(tpl.read_text(encoding="utf-8"))
    assert "language" not in data
    assert "theme" not in data
