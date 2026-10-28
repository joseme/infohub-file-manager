"""Ediciones Business / Enterprise del File Manager.

La edición la decide InfoHub (GET /api/v1/system → settings.Edition). Lo de
ee/ se activa solo si InfoHub es Enterprise y el paquete ee está presente; la
imagen Business se construye sin él.
"""

import logging

import requests

try:
    import ee
except ImportError:  # imagen Business
    ee = None

logger = logging.getLogger(__name__)

EDITIONS = ("business", "enterprise")


def fetch_edition(base_url: str, api_key: str, timeout: int = 10) -> str:
    """Edición de InfoHub. Ante cualquier error, o un InfoHub sin el campo, Business."""
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/api/v1/system",
            headers={"Authorization": f"Bearer {api_key}", "accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning(f"No se pudo leer la edición de InfoHub: {resp.status_code}")
            return "business"
        value = (resp.json().get("settings") or {}).get("Edition")
        return value if value in EDITIONS else "business"
    except Exception as e:
        logger.warning(f"No se pudo leer la edición de InfoHub: {e}")
        return "business"


def is_enterprise(edition: str, ee_module=ee) -> bool:
    return ee_module is not None and edition == "enterprise"
