"""Funciones opcionales del File Manager, activadas por la licencia de InfoHub.

InfoHub decide qué funciones tiene cada cliente con una licencia firmada y las
expone en GET /api/v1/system → settings.Features (lista de ids). Una función
paga se muestra solo si su id está en la lista:

    if features.is_enabled(current_features, "auditoria"):
        ...
"""

import logging

import requests

logger = logging.getLogger(__name__)


def fetch_features(base_url: str, api_key: str, timeout: int = 10) -> list[str]:
    """Ids de las funciones activas. Ante cualquier error, o un InfoHub sin el campo, ninguna."""
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/api/v1/system",
            headers={"Authorization": f"Bearer {api_key}", "accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning(f"No se pudieron leer las funciones de InfoHub: {resp.status_code}")
            return []
        value = (resp.json().get("settings") or {}).get("Features")
        if not isinstance(value, list):
            return []
        return [f for f in value if isinstance(f, str)]
    except Exception as e:
        logger.warning(f"No se pudieron leer las funciones de InfoHub: {e}")
        return []


def is_enabled(current_features: list[str], feature_id: str) -> bool:
    return feature_id in current_features
