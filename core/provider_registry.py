"""
Provider Registry — open registry pattern for multi-platform video providers.
New providers (Facebook, TikTok, etc.) only need to call register() at import time.
"""
from typing import Dict, Type, List
from core.base_provider import VideoProvider

_REGISTRY: Dict[str, Type[VideoProvider]] = {}


def register(provider_id: str, cls: Type[VideoProvider]):
    """Register a provider class by ID. Called in each provider's __init__.py."""
    _REGISTRY[provider_id] = cls


def get(provider_id: str) -> VideoProvider:
    """Instantiate and return a provider by ID."""
    cls = _REGISTRY.get(provider_id)
    if not cls:
        available = list(_REGISTRY.keys())
        raise ValueError(f"Unknown provider '{provider_id}'. Available: {available}")
    return cls()


def list_providers() -> List[dict]:
    """List all registered providers with metadata."""
    result = []
    for pid, cls in _REGISTRY.items():
        result.append({
            "id": pid,
            "name": getattr(cls, "provider_name", pid),
            "icon": getattr(cls, "provider_icon", "📹"),
        })
    return result


def is_registered(provider_id: str) -> bool:
    return provider_id in _REGISTRY
