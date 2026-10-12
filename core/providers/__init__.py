"""Model provider factory and package exports."""

from __future__ import annotations

from core.providers.base import ModelProvider, ProviderError
from core.providers.github import GitHubCopilotProvider
from core.providers.ollama import OllamaProvider
from core.providers.openai_compatible import OpenAICompatibleProvider


def _url(provider_cfg: dict, default: str, secrets: dict | None = None) -> str:
    value = provider_cfg.get("url") or default
    return value.rstrip("/")


def _vision(provider_cfg: dict) -> bool:
    """Model-level vision switch (provider.vision); defaults to enabled."""
    return bool(provider_cfg.get("vision", True))


def preset_url(provider_type: str) -> str:
    """Base URL preset for a provider type (what Settings shows on switch).

    Single source for the fallbacks create_provider would use — the Settings
    URL field is reset to this on a provider-type change (B18) so a custom
    URL from the previous provider never receives the new provider's key.
    """
    if provider_type == "ollama":
        return "http://127.0.0.1:11434"
    if provider_type == "openai_compatible":
        return "https://api.openai.com/v1"
    if provider_type == "github":
        return "https://api.github.com/copilot"
    preset = _OPENAI_COMPATIBLE_PRESETS.get(provider_type)
    return preset[0] if preset else ""


# Standard OpenAI-compatible presets: provider type -> (default base_url,
# secrets key). Special-cased types (openai_compatible's secret fallback,
# nararouter's URL trimming) live in create_provider directly.
_OPENAI_COMPATIBLE_PRESETS: dict[str, tuple[str, str]] = {
    "nvidia": ("https://integrate.api.nvidia.com/v1", "nvidia_api_key"),
    "groq": ("https://api.groq.com/openai/v1", "groq_api_key"),
    "google": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "google_api_key",
    ),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek_api_key"),
    "mistral": ("https://api.mistral.ai/v1", "mistral_api_key"),
    "xai": ("https://api.x.ai/v1", "xai_api_key"),
    "together": ("https://api.together.xyz/v1", "together_api_key"),
    "openrouter": ("https://openrouter.ai/api/v1", "openrouter_api_key"),
}


def create_provider(
    settings: dict, secrets: dict, session=None
) -> ModelProvider:
    provider_cfg = settings.get("provider") or {}
    ptype = provider_cfg.get("type", "ollama")
    if ptype == "openai_compat":  # legacy settings value, pre-rename
        ptype = "openai_compatible"
    timeout_s = float((settings.get("agent") or {}).get("model_timeout_s", 60))
    vision = _vision(provider_cfg)
    if ptype == "ollama":
        return OllamaProvider(
            base_url=_url(provider_cfg, "http://127.0.0.1:11434"),
            model=provider_cfg.get("model", "llama3.2"),
            api_key=secrets.get("ollama_api_key"),
            timeout_s=timeout_s,
            session=session,
            supports_vision=vision,
        )
    if ptype == "openai_compatible":
        api_key = secrets.get("api_key") or secrets.get("openai_api_key")
        if not api_key:
            raise ProviderError(
                "openai_compatible provider requires secrets.api_key",
                error_code="missing_api_key",
            )
        return OpenAICompatibleProvider(
            base_url=_url(provider_cfg, "https://api.openai.com/v1"),
            api_key=api_key,
            model=provider_cfg.get("model"),
            timeout_s=timeout_s,
            session=session,
            supports_vision=vision,
            provider_key=ptype,
        )
    if ptype == "github":
        api_key = secrets.get("github_api_key")
        if not api_key:
            raise ProviderError(
                "github provider requires secrets.github_api_key",
                error_code="missing_api_key",
            )
        return GitHubCopilotProvider(
            api_key=api_key,
            model=provider_cfg.get("model", "gpt-4o"),
            timeout_s=timeout_s,
            session=session,
            supports_vision=vision,
        )
    preset = _OPENAI_COMPATIBLE_PRESETS.get(ptype)
    if preset:
        default_url, secret_key = preset
        api_key = secrets.get(secret_key)
        if not api_key:
            raise ProviderError(
                f"{ptype} provider requires secrets.{secret_key}",
                error_code="missing_api_key",
            )
        return OpenAICompatibleProvider(
            base_url=_url(provider_cfg, default_url),
            api_key=api_key,
            model=provider_cfg.get("model"),
            timeout_s=timeout_s,
            session=session,
            supports_vision=vision,
            provider_key=ptype,
        )
    if ptype == "nararouter":
        api_key = secrets.get("nararouter_api_key")
        if not api_key:
            raise ProviderError(
                "nararouter provider requires secrets.nararouter_api_key",
                error_code="missing_api_key",
            )
        url = _url(provider_cfg, "") or secrets.get(
            "openai_compatible_url_for_nararouter", ""
        )
        url = url.rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        return OpenAICompatibleProvider(
            base_url=url,
            api_key=api_key,
            model=provider_cfg.get("model"),
            timeout_s=timeout_s,
            session=session,
            supports_vision=vision,
            provider_key=ptype,
        )
    raise ProviderError(f"unknown provider type: {ptype}", error_code="unknown_provider")
