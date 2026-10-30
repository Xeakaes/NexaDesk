"""Wire config + providers + tools + runtime into an AgentRuntime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.agent.config import AgentConfig
from core.agent.runtime import AgentRuntime
from core.config import ensure_secrets_mode, load_secrets, load_settings
from core.events import EventBus
from core.mcp.client import MCPServerConfig
from core.mcp.mapping import register_mcp_tools
from core.paths import config_dir
from core.providers import create_provider
from core.providers.base import ModelProvider
from core.session.store import SessionStore
from core.tools.registry import PermissionPolicy, ToolRegistry
from core.tools.screen_control import SCREEN_CONTROL_TOOL_NAMES, register_screen_control

DEFAULT_SETTINGS = config_dir() / "settings.json"
DEFAULT_SECRETS = config_dir() / "secrets.json"


def live_screen_control_token() -> str | None:
    """Read the running screen-control server's session token.

    The server regenerates its session token on every start and writes it to
    ``$SCREEN_CONTROL_DATA_DIR/.token`` (the same ``config_dir()`` we spawn it
    with). The ``screen_control_api_key`` cached in secrets goes stale after a
    server restart, so callers must prefer this live token and fall back to
    secrets only when the file is unavailable.
    """
    token_file = config_dir() / ".token"
    try:
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            return token or None
    except OSError:
        pass
    return None


def default_client_factory(settings: dict, secrets: dict) -> Callable[[], Any]:
    def factory():
        from vendor.sc_server.sdk import ScreenControl  # lazy — only when a tool runs

        sc_cfg = settings.get("screen_control") or {}
        # Prefer the LIVE server token over the (possibly stale) cached secrets
        # value — otherwise every tool call 401s after the server restarts.
        token = live_screen_control_token() or secrets.get(
            "screen_control_api_key"
        )
        return ScreenControl(
            host=sc_cfg.get("host", "127.0.0.1"),
            port=int(sc_cfg.get("port", 8745)),
            api_key=token,
        )

    return factory


def apply_screen_control_settings(
    registry: ToolRegistry, settings: dict, secrets: dict
) -> None:
    """Re-register screen-control tools from freshly saved settings (B29).

    The factory captured at ``build_runtime`` time pinned the startup host,
    port, and API key; after the user saves Settings the live registry must
    follow the new config — including enabled/disabled — without an app
    restart.
    """
    for name in SCREEN_CONTROL_TOOL_NAMES:
        registry.unregister(name)
    sc_cfg = settings.get("screen_control") or {}
    if sc_cfg.get("enabled", False):
        register_screen_control(registry, default_client_factory(settings, secrets))


def build_runtime(
    settings_path: Path | None = None,
    secrets_path: Path | None = None,
    provider: ModelProvider | None = None,
    client_factory: Callable[[], Any] | None = None,
) -> tuple[AgentRuntime, EventBus, SessionStore]:
    settings = load_settings(settings_path or DEFAULT_SETTINGS)
    secrets_path = secrets_path or DEFAULT_SECRETS
    if secrets_path.exists():
        ensure_secrets_mode(secrets_path)
        secrets = load_secrets(secrets_path)
    else:
        secrets = {}
    if provider is None:
        provider = create_provider(settings, secrets)
    registry = ToolRegistry()
    sc_cfg = settings.get("screen_control") or {}
    if sc_cfg.get("enabled", False):
        factory = client_factory or default_client_factory(settings, secrets)
        register_screen_control(registry, factory)
    mcp_cfg = settings.get("mcp") or {}
    mcp_clients = []
    if mcp_cfg.get("enabled", False):
        mcp_configs = [
            MCPServerConfig.from_dict(server)
            for server in (mcp_cfg.get("servers") or [])
        ]
        mcp_clients = register_mcp_tools(registry, mcp_configs)
    policy = PermissionPolicy(settings.get("permissions") or {"*": "ask"})
    agent_cfg_raw = settings.get("agent") or {}
    agent_config = AgentConfig(
        max_tool_calls=int(agent_cfg_raw.get("max_tool_calls", 10)),
        tool_timeout_s=float(agent_cfg_raw.get("tool_timeout_s", 30)),
        model_timeout_s=float(agent_cfg_raw.get("model_timeout_s", 60)),
        max_history_images=int(agent_cfg_raw.get("max_history_images", 1)),
        persona=str(agent_cfg_raw.get("persona", "")),
    )
    events = EventBus()
    session = SessionStore()
    runtime = AgentRuntime(provider, registry, policy, events, session, agent_config)
    for client in mcp_clients:
        runtime.on_close(client.close)
    return runtime, events, session
