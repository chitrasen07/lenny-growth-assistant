"""Provider construction and lifecycle.

Providers are cached per name so a single HTTP connection pool is reused across requests.

There is intentionally **no automatic fallback** between providers: silently answering a
"local Ollama" request with a cloud model would misrepresent what the demo is doing, and
silently doing the reverse would change answer quality with no signal. A provider failure
returns a typed error naming the fix instead.
"""

from __future__ import annotations

from app.core.config import LLMProviderName, Settings, get_settings
from app.core.errors import ProviderConfigurationError
from app.providers.anthropic import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.ollama import OllamaProvider

_cache: dict[str, LLMProvider] = {}


def get_provider(name: LLMProviderName | None = None, settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    resolved = name or settings.llm_provider

    if resolved in _cache:
        return _cache[resolved]

    if resolved is LLMProviderName.OLLAMA:
        provider: LLMProvider = OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.llm_timeout_seconds,
            embedding_model=settings.embedding_model,
        )
    elif resolved is LLMProviderName.ANTHROPIC:
        provider = AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout=settings.llm_timeout_seconds,
        )
    else:  # pragma: no cover - unreachable while LLMProviderName is exhaustive
        raise ProviderConfigurationError(
            f"Unknown LLM provider '{resolved}'.",
            remedy="Set LLM_PROVIDER to 'ollama' or 'anthropic'.",
        )

    _cache[resolved] = provider
    return provider


def register_provider(name: LLMProviderName, provider: LLMProvider) -> None:
    """Test hook: install a fake provider for a given name."""
    _cache[name] = provider


def clear_providers() -> None:
    """Test hook: drop cached providers so registrations cannot leak between tests."""
    _cache.clear()


async def close_providers() -> None:
    for provider in list(_cache.values()):
        await provider.aclose()
    _cache.clear()
