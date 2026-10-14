import pytest

from ui.i18n import I18n, LANGUAGES, MissingTranslationError, STRINGS, i18n


def test_languages_exact():
    assert LANGUAGES == ("tr", "en")


def test_every_key_has_both_languages():
    assert STRINGS
    for key, entry in STRINGS.items():
        assert set(entry) == set(LANGUAGES), key
        for lang in LANGUAGES:
            assert entry[lang].strip(), f"{key}/{lang} empty"


def test_expected_keys_exist():
    expected = (
        "app.title",
        "sidebar.new_chat",
        "settings.theme",
        "chat.send",
        "mode.choose_title",
        "menu.switch_gui",
        "settings.pack_build",
    )
    for k in expected:
        assert k in STRINGS


def test_missing_key_raises():
    i = I18n("tr")
    with pytest.raises(MissingTranslationError):
        i.t("does.not.exist")


def test_language_switch_changes_output():
    i = I18n("tr")
    assert i.t("chat.send") == STRINGS["chat.send"]["tr"]
    i.set_language("en")
    assert i.t("chat.send") == STRINGS["chat.send"]["en"]


def test_format_placeholders():
    s = I18n("tr")
    STRINGS["__test_fmt"] = {"tr": "Merhaba {name}", "en": "Hello {name}"}
    try:
        assert s.t("__test_fmt", name="Ada") == "Merhaba Ada"
    finally:
        del STRINGS["__test_fmt"]


def test_unknown_language_raises():
    with pytest.raises(ValueError):
        I18n("fr")


def test_avatar_boot_failed_key_is_translated():
    # B75: the avatar boot error was hard-coded Turkish even for English
    # users ("Agent başlatılamadı: ...").
    i18n.set_language("en")
    try:
        msg = i18n.t("avatar.boot_failed", error="boom")
        assert "başlatılamadı" not in msg
        assert "could not start" in msg.lower() or "failed" in msg.lower()
    finally:
        i18n.set_language("tr")
