import importlib
import sys


def test_sdk_importable_from_vendor():
    mod = importlib.import_module("vendor.sc_server.sdk")
    assert hasattr(mod, "ScreenControl")


def test_vendor_packages_renamed():
    sc_core_backends = importlib.import_module("vendor.sc_server.sc_core.backends")
    assert sc_core_backends.__name__ == "vendor.sc_server.sc_core.backends"
    import core

    assert not hasattr(core, "backends")


def test_server_module_importable():
    pytest_importorskip = __import__("pytest").importorskip
    pytest_importorskip("flask")
    mod = importlib.import_module("vendor.sc_server.server")
    assert hasattr(mod, "main")


def test_server_token_dir_uses_env(monkeypatch, tmp_path):
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    # force fresh module so env is read at import time
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    mod = importlib.import_module("vendor.sc_server.server")
    assert str(tmp_path) in mod.SESSION_TOKEN_FILE
    assert str(tmp_path) in mod.APIKEYS_FILE


def test_server_import_does_not_write_token(monkeypatch, tmp_path):
    # A racing second spawn imports this module before knowing it cannot
    # bind; an import-time token write would clobber the LIVE server's
    # token and 401 every subsequent tool call.
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    (tmp_path / ".token").write_text("LIVE_TOKEN")
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    importlib.import_module("vendor.sc_server.server")
    assert (tmp_path / ".token").read_text() == "LIVE_TOKEN"


def test_write_session_token_is_secure(monkeypatch, tmp_path):
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    mod = importlib.import_module("vendor.sc_server.server")
    mod._write_session_token()
    p = tmp_path / ".token"
    assert p.read_text() == mod.SESSION_TOKEN
    if __import__("os").name == "posix":
        assert (p.stat().st_mode & 0o777) == 0o600


def test_save_api_keys_is_private(monkeypatch, tmp_path):
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    mod = importlib.import_module("vendor.sc_server.server")
    mod._api_key_names["a" * 64] = "test-key"
    mod._save_api_keys()
    p = tmp_path / ".apikeys"
    assert p.exists()
    if __import__("os").name == "posix":
        assert (p.stat().st_mode & 0o777) == 0o600


def test_default_client_factory_uses_vendor(monkeypatch):
    import core.bootstrap as b

    src = __import__("pathlib").Path(b.__file__).read_text()
    assert "/home/xeakaes/screen-control" not in src
    assert "vendor.sc_server.sdk" in src
