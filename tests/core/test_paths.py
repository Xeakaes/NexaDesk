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
