"""First-run setup helpers: survive a missing provider API key gracefully.

A fresh install ships a settings template (provider=groq) but no secrets, so
``create_provider`` raises ``missing_api_key`` at startup. Instead of crashing,
the UI builds the runtime with :class:`UnconfiguredProvider` and guides the
user to the Settings window; once they save, :func:`reload_provider` swaps in
the real provider without a restart.
"""

from __future__ import annotations

from pathlib import Path

from core.agent.cancellation import CancellationToken
from core.config import load_secrets, load_settings
from core.providers import create_provider
from core.providers.base import (
    ChatMessage,
    ModelProvider,
    ProviderError,
    ProviderResponse,
)
from core.bootstrap import apply_screen_control_settings


class UnconfiguredProvider(ModelProvider):
    """Stand-in used until the user configures a real provider in Settings."""

    supports_tools = False
    supports_vision = False

    def complete(
        self,
        messages: list[ChatMessage],
        schemas: list[dict],
        cancel: CancellationToken,
    ) -> ProviderResponse:
        raise ProviderError(
            "provider is not configured yet — open Settings to set up the model",
            error_code="provider_not_configured",
        )


def is_missing_key_error(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.error_code == "missing_api_key"


def reload_provider(runtime, settings_path: Path, secrets_path: Path) -> bool:
    """Recreate the real provider from disk and hot-swap it into the runtime.

    Returns True if a working provider was installed; False if the config is
    still incomplete (the placeholder stays active).
    """
    settings = load_settings(settings_path)
    secrets = load_secrets(secrets_path) if secrets_path.exists() else {}
    try:
        provider = create_provider(settings, secrets)
    except ProviderError:
        return False
    runtime.set_provider(provider)
    return True


def apply_screen_control(runtime, settings_path: Path, secrets_path: Path) -> None:
    """Re-register screen-control tools from freshly saved settings (B29).

    Mirrors :func:`reload_provider`: paths in, live registry updated — the
    user's new host/port/key (or enable/disable) applies without a restart.
    """
    settings = load_settings(settings_path)
    secrets = load_secrets(secrets_path) if secrets_path.exists() else {}
    apply_screen_control_settings(runtime.registry, settings, secrets)
