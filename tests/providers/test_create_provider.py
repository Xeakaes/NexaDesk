import pytest
from core.providers import create_provider
from core.providers.base import ProviderError
from core.providers.ollama import OllamaProvider
from core.providers.openai_compatible import OpenAICompatibleProvider


def test_create_ollama_provider():
    p = create_provider(
        {"provider": {"type": "ollama", "url": "http://127.0.0.1:11434", "model": "m"}},
        {},
    )
    assert isinstance(p, OllamaProvider) and p.model == "m"


def test_create_openai_compat_requires_api_key():
    with pytest.raises(ProviderError) as ei:
        create_provider({"provider": {"type": "openai_compatible", "model": "m"}}, {})
    assert ei.value.error_code == "missing_api_key"


def test_create_openai_compat_uses_api_key_secret():
    p = create_provider(
        {"provider": {"type": "openai_compatible", "url": "http://x/v1", "model": "m"}},
        {"api_key": "sk-test"},
    )
    assert isinstance(p, OpenAICompatibleProvider) and p.api_key == "sk-test"


def test_create_nvidia_profile():
    p = create_provider(
        {"provider": {"type": "nvidia", "model": "meta/llama-3.1-8b-instruct"}},
        {"nvidia_api_key": "nvapi-x"},
    )
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.api_key == "nvapi-x"
    assert "integrate.api.nvidia.com" in p.base_url


def test_create_nararouter_profile_strips_chat_completions():
    p = create_provider(
        {"provider": {"type": "nararouter", "model": "m"}},
        {
            "nararouter_api_key": "sk-nry-x",
            "openai_compatible_url_for_nararouter": "https://router.example/v1/chat/completions",
        },
    )
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.base_url == "https://router.example/v1"
    assert p.api_key == "sk-nry-x"


def test_create_unknown_type():
    with pytest.raises(ProviderError) as ei:
        create_provider({"provider": {"type": "nope"}}, {})
    assert ei.value.error_code == "unknown_provider"


def test_create_groq_profile():
    p = create_provider(
        {"provider": {"type": "groq", "model": "qwen/qwen3.8-27b"}},
        {"groq_api_key": "gsk_x"},
    )
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.api_key == "gsk_x"
    assert "api.groq.com" in p.base_url
    assert p.base_url.endswith("/openai/v1")


def test_create_groq_missing_key():
    with pytest.raises(ProviderError) as ei:
        create_provider({"provider": {"type": "groq"}}, {})
    assert ei.value.error_code == "missing_api_key"


def test_create_google_profile():
    p = create_provider(
        {"provider": {"type": "google", "model": "gemini-3.8-flash"}},
        {"google_api_key": "AIza-x"},
    )
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.api_key == "AIza-x"
    assert "generativelanguage.googleapis.com" in p.base_url
    assert p.base_url.endswith("/v1beta/openai")


def test_create_google_missing_key():
    with pytest.raises(ProviderError) as ei:
        create_provider({"provider": {"type": "google"}}, {})
    assert ei.value.error_code == "missing_api_key"


def test_create_groq_empty_url_uses_default():
    p = create_provider(
        {"provider": {"type": "groq", "url": "", "model": "m"}},
        {"groq_api_key": "gsk_x"},
    )
    assert p.base_url == "https://api.groq.com/openai/v1"


def test_create_openai_compat_empty_url_uses_openai_default():
    p = create_provider(
        {"provider": {"type": "openai_compatible", "url": "", "model": "m"}},
        {"api_key": "sk-x"},
    )
    assert p.base_url == "https://api.openai.com/v1"


def test_create_ollama_empty_url_uses_default():
    p = create_provider(
        {"provider": {"type": "ollama", "url": "", "model": "m"}},
        {},
    )
    assert p.base_url == "http://127.0.0.1:11434"


def test_create_nvidia_empty_url_uses_default():
    p = create_provider(
        {"provider": {"type": "nvidia", "url": "", "model": "m"}},
        {"nvidia_api_key": "nvapi-x"},
    )
    assert p.base_url == "https://integrate.api.nvidia.com/v1"


def test_create_google_empty_url_uses_default():
    p = create_provider(
        {"provider": {"type": "google", "url": "", "model": "m"}},
        {"google_api_key": "AIza-x"},
    )
    assert "generativelanguage.googleapis.com" in p.base_url


def test_create_provider_vision_flag_false():
    p = create_provider(
        {"provider": {"type": "groq", "model": "m", "vision": False}},
        {"groq_api_key": "gsk_x"},
    )
    assert p.supports_vision is False


def test_create_provider_vision_default_true():
    p = create_provider(
        {"provider": {"type": "groq", "model": "m"}},
        {"groq_api_key": "gsk_x"},
    )
    assert p.supports_vision is True


def test_create_ollama_vision_flag_false():
    p = create_provider(
        {"provider": {"type": "ollama", "model": "m", "vision": False}},
        {},
    )
    assert p.supports_vision is False


@pytest.mark.parametrize(
    "ptype,secret,base_frag",
    [
        ("deepseek", "deepseek_api_key", "api.deepseek.com"),
        ("mistral", "mistral_api_key", "api.mistral.ai"),
        ("xai", "xai_api_key", "api.x.ai"),
        ("together", "together_api_key", "api.together.xyz"),
        ("openrouter", "openrouter_api_key", "openrouter.ai"),
    ],
)
def test_create_popular_presets(ptype, secret, base_frag):
    p = create_provider({"provider": {"type": ptype, "model": "m"}}, {secret: "k-x"})
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.api_key == "k-x"
    assert base_frag in p.base_url
    assert p.provider_key == ptype


@pytest.mark.parametrize(
    "ptype", ["deepseek", "mistral", "xai", "together", "openrouter"]
)
def test_popular_presets_missing_key(ptype):
    with pytest.raises(ProviderError) as ei:
        create_provider({"provider": {"type": ptype}}, {})
    assert ei.value.error_code == "missing_api_key"


def test_create_github_copilot_profile():
    from core.providers.github import GitHubCopilotProvider

    p = create_provider(
        {"provider": {"type": "github", "model": "gpt-4o"}},
        {"github_api_key": "ghp_x"},
    )
    assert isinstance(p, GitHubCopilotProvider)
    assert p.api_key == "ghp_x"
    assert p.provider_key == "github"
    assert p.base_url == "https://api.github.com/copilot"


def test_create_github_default_model():
    from core.providers.github import GitHubCopilotProvider

    p = create_provider({"provider": {"type": "github"}}, {"github_api_key": "ghp_x"})
    assert isinstance(p, GitHubCopilotProvider)
    assert p.model == "gpt-4o"


def test_create_github_missing_key():
    with pytest.raises(ProviderError) as ei:
        create_provider({"provider": {"type": "github"}}, {})
    assert ei.value.error_code == "missing_api_key"


def test_legacy_openai_compat_type_still_accepted():
    # Settings saved before the rename keep type "openai_compat".
    p = create_provider(
        {"provider": {"type": "openai_compat", "url": "http://x/v1", "model": "m"}},
        {"api_key": "sk-test"},
    )
    assert isinstance(p, OpenAICompatibleProvider) and p.api_key == "sk-test"


def test_preset_url_matches_create_provider_defaults():
    # B18: the Settings URL reset must use exactly the defaults
    # create_provider would fall back to — one source, no drift.
    from core.providers import _OPENAI_COMPATIBLE_PRESETS, preset_url

    assert preset_url("ollama") == "http://127.0.0.1:11434"
    assert preset_url("openai_compatible") == "https://api.openai.com/v1"
    assert preset_url("github") == "https://api.github.com/copilot"
    assert preset_url("nararouter") == ""
    for ptype, (url, _key) in _OPENAI_COMPATIBLE_PRESETS.items():
        assert preset_url(ptype) == url
