import os
import sys

import pytest

from core import paths


def test_dev_config_dir_unchanged(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert paths.config_dir() == paths.repo_root() / "config"


def test_config_dir_frozen_uses_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    if os.name == "nt":
        assert paths.config_dir() == tmp_path / "appdata" / "NexaDesk"
    else:
        assert paths.config_dir() == tmp_path / ".config" / "NexaDesk"


def test_bundle_root_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "b"), raising=False)
    assert paths.bundle_root() == tmp_path / "b"


def test_bundled_version_prefers_version_file(monkeypatch, tmp_path):
    # B10: the packaged app writes the real version into _version.txt at
    # build time; the update check must compare against that, not 0.0.0.
    monkeypatch.delenv("APP_VERSION", raising=False)
    (tmp_path / "_version.txt").write_text("0.2.1\n", encoding="utf-8")
    monkeypatch.setattr(paths, "bundle_root", lambda: tmp_path)
    assert paths.bundled_version() == "0.2.1"


def test_bundled_version_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    (tmp_path / "_version.txt").write_text("9.9.9", encoding="utf-8")
    monkeypatch.setattr(paths, "bundle_root", lambda: tmp_path)
    assert paths.bundled_version() == "1.2.3"


def test_bundled_version_falls_back_to_core_version(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.setattr(paths, "bundle_root", lambda: tmp_path)  # no _version.txt
    from core import __version__

    assert paths.bundled_version() == __version__


def test_bundled_version_ignores_blank_file(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    (tmp_path / "_version.txt").write_text("   \n", encoding="utf-8")
    monkeypatch.setattr(paths, "bundle_root", lambda: tmp_path)
    from core import __version__

    assert paths.bundled_version() == __version__


def test_assets_dir_dev(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert paths.assets_dir() == paths.repo_root() / "assets"


def test_data_dir_creates(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    d = paths.data_dir()
    assert d.exists() and d.is_dir()
    if os.name != "nt":
        assert d == tmp_path / ".local" / "share" / "NexaDesk"


def test_ensure_user_config_seeds_from_template(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    tpl = tmp_path / "bundle" / "config_template"
    tpl.mkdir(parents=True)
    (tpl / "settings.json").write_text('{"provider": {"type": "groq"}}', encoding="utf-8")
    paths.ensure_user_config()
    cfg = paths.config_dir()
    settings = cfg / "settings.json"
    assert settings.exists()
    assert "groq" in settings.read_text(encoding="utf-8")
    secrets = cfg / "secrets.json"
    assert secrets.exists()
    if os.name != "nt":
        assert secrets.stat().st_mode & 0o777 == 0o600


def test_create_empty_secrets_creates_private_file(tmp_path):
    # Created via O_EXCL + 0600 so the file is never world-readable, not even
    # for the instant between creation and a later chmod.
    p = tmp_path / "secrets.json"
    paths.create_empty_secrets(p)
    assert p.exists()
    if os.name != "nt":
        assert p.stat().st_mode & 0o777 == 0o600


def test_create_empty_secrets_never_overwrites(tmp_path):
    p = tmp_path / "secrets.json"
    p.write_text('{"api_key": "live"}', encoding="utf-8")
    paths.create_empty_secrets(p)  # must be a no-op, not clobber the keys
    assert p.read_text(encoding="utf-8") == '{"api_key": "live"}'


def test_ensure_user_config_writes_defaults_without_template(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "empty-bundle"), raising=False)
    (tmp_path / "empty-bundle").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    paths.ensure_user_config()
    settings = paths.config_dir() / "settings.json"
    assert settings.exists()
    assert "screen_control" in settings.read_text(encoding="utf-8")


def test_ensure_user_config_noop_when_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "b"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    cfg = paths.config_dir()
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text('{"keep": true}', encoding="utf-8")
    paths.ensure_user_config()
    assert (cfg / "settings.json").read_text(encoding="utf-8") == '{"keep": true}'


def test_migrate_legacy_dirs_moves_data_and_config(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "b"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    if os.name == "nt":
        pytest.skip("windows legacy dir layout differs")
    legacy_cfg = tmp_path / ".config" / "desktop-assistant"
    legacy_data = tmp_path / ".local" / "share" / "desktop-assistant"
    legacy_cfg.mkdir(parents=True)
    legacy_data.mkdir(parents=True)
    (legacy_cfg / "secrets.json").write_text('{"k": 1}', encoding="utf-8")
    (legacy_data / "history.db").write_bytes(b"sqlite")
    paths.migrate_legacy_dirs()
    assert (paths.config_dir() / "secrets.json").read_text(encoding="utf-8") == '{"k": 1}'
    assert (paths.data_dir() / "history.db").read_bytes() == b"sqlite"
    assert not legacy_cfg.exists()
    assert not legacy_data.exists()


def test_migrate_legacy_dirs_does_not_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "b"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    if os.name == "nt":
        pytest.skip("windows legacy dir layout differs")
    legacy_data = tmp_path / ".local" / "share" / "desktop-assistant"
    legacy_data.mkdir(parents=True)
    (legacy_data / "history.db").write_bytes(b"old")
    new_data = paths.data_dir()
    (new_data / "history.db").write_bytes(b"new")
    paths.migrate_legacy_dirs()
    assert (new_data / "history.db").read_bytes() == b"new"


def test_config_dir_frozen_honors_xdg_config_home(monkeypatch, tmp_path):
    # B55: frozen Linux builds must respect XDG_CONFIG_HOME.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgcfg"))
    assert paths.config_dir() == tmp_path / "xdgcfg" / "NexaDesk"


def test_data_dir_honors_xdg_data_home(monkeypatch, tmp_path):
    # B55: frozen Linux builds must respect XDG_DATA_HOME.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdgdata"))
    d = paths.data_dir()
    assert d == tmp_path / "xdgdata" / "NexaDesk"
    assert d.exists()


def test_migrate_legacy_dirs_runs_once_via_marker(monkeypatch, tmp_path):
    # B53: the migration must not re-scan/re-move on every launch; a marker
    # file gates it after the first successful run.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "b"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    if os.name == "nt":
        pytest.skip("windows legacy dir layout differs")
    legacy_cfg = tmp_path / ".config" / "desktop-assistant"
    legacy_cfg.mkdir(parents=True)
    (legacy_cfg / "secrets.json").write_text('{"k": 1}', encoding="utf-8")
    paths.migrate_legacy_dirs()
    assert (paths.config_dir() / "secrets.json").exists()
    assert (paths.config_dir() / ".legacy_migrated").exists()
    # second run: create a new legacy dir+file; migration must skip (marker)
    legacy_cfg.mkdir(parents=True, exist_ok=True)
    (legacy_cfg / "more.json").write_text("{}", encoding="utf-8")
    paths.migrate_legacy_dirs()
    assert not (paths.config_dir() / "more.json").exists()


def test_window_icon_path_finds_repo_icon():
    # B52: the window/tray icon must resolve from the repo in dev mode.
    p = paths.window_icon_path()
    assert p is not None and p.is_file() and p.suffix == ".png"


def test_settings_template_is_valid_json():
    # B57: the tracked template must stay parseable and free of live edits.
    import json

    tpl = paths.repo_root() / "config_template" / "settings.json"
    data = json.loads(tpl.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "avatar" in data
    # no secrets or provider keys may ship in the template
    blob = tpl.read_text(encoding="utf-8").lower()
    assert "api_key" not in blob and "token" not in blob
