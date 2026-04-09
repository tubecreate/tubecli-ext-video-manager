"""
Provider Registry — open registry pattern for multi-platform video providers.
New providers (Facebook, TikTok, etc.) only need to call register() at import time.
"""
import os
import sys
import logging
import importlib.util
from typing import Dict, Type, List
from core.base_provider import VideoProvider

logger = logging.getLogger("ProviderRegistry")

_REGISTRY: Dict[str, Type[VideoProvider]] = {}


def register(provider_id: str, cls: Type[VideoProvider]):
    """Register a provider class by ID. Called in each provider's __init__.py."""
    _REGISTRY[provider_id] = cls


def get(provider_id: str) -> VideoProvider:
    """Instantiate and return a provider by ID."""
    if provider_id not in _REGISTRY:
        _auto_load_provider(provider_id)

    cls = _REGISTRY.get(provider_id)
    if not cls:
        available = list(_REGISTRY.keys())
        raise ValueError(f"Unknown provider '{provider_id}'. Available: {available}")
    return cls()


def _auto_load_provider(provider_id: str):
    """Auto-load a provider module by exact file path to avoid namespace collisions."""
    ext_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(ext_dir, "providers", provider_id, "__init__.py")

    if not os.path.exists(target):
        return

    try:
        # Use a unique module name to avoid clashing with other extensions
        mod_name = f"vidmgr_provider_{provider_id}"
        spec = importlib.util.spec_from_file_location(mod_name, target)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)

        # The module should self-register via register(), but if not,
        # try to find and register the provider class directly
        if provider_id not in _REGISTRY:
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (isinstance(attr, type) and issubclass(attr, VideoProvider)
                        and attr is not VideoProvider
                        and getattr(attr, "provider_id", None) == provider_id):
                    register(provider_id, attr)
                    break

        logger.info(f"Auto-loaded video provider: {provider_id}")
    except Exception as e:
        logger.error(f"Failed to auto-load video provider {provider_id}: {e}")


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
