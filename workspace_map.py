"""Resolución del slug real de un workspace de InfoHub a partir de su nombre.

El panel calculaba el slug con una regla local
('Legislación Laboral CR' -> 'legislacion-laboral-cr'), pero el servidor usa
slugs propios ('Tributación CR' -> 'tributacion', 'Legislación Seguros CR' ->
'seguros-cr'). Con la regla local el panel creaba workspaces duplicados.

Este módulo consulta GET /api/v1/workspaces, indexa los workspaces por forma
canónica del nombre (minúsculas, sin acentos ni puntuación) y devuelve el slug
real. Si no hay coincidencia aplica la regla antigua, y el llamador decide si
crea el workspace.

Lo usan app.py (panel) y sync_bot.py (bot headless).
"""

import re
import time
import requests

_ACCENT_MAP = str.maketrans({
    "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
    "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
})

# Alias nombre de carpeta local -> nombre del workspace en el servidor.
ALIASES = {
    "odoo": "odoo17",
}


def canonical(s: str) -> str:
    """Forma canónica para comparar nombres ('' si queda vacío)."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().translate(_ACCENT_MAP))


def slug_naive(name: str) -> str:
    """Regla antigua del panel, usada solo como respaldo."""
    return (name or "").lower().replace(" ", "-").replace("_", "-")


class WorkspaceResolver:
    """Índice {canonical(nombre): slug} del servidor, con caché y alias locales."""

    def __init__(self, base_url: str, api_key: str, aliases: dict | None = None, ttl: int = 600):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.aliases = dict(ALIASES)
        if aliases:
            self.aliases.update(aliases)
        self.ttl = ttl
        self._index: dict[str, str] | None = None
        self._names: dict[str, str] = {}
        self._loaded_at = 0.0

    # --- consulta al servidor -------------------------------------------------
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "accept": "application/json"}

    def refresh(self) -> dict:
        """Recarga el índice desde el servidor. Devuelve {canonical: slug}."""
        resp = requests.get(f"{self.base_url}/api/v1/workspaces", headers=self._headers(), timeout=20)
        resp.raise_for_status()
        index, names = {}, {}
        for ws in resp.json().get("workspaces", []):
            slug, name = ws.get("slug"), ws.get("name") or ws.get("slug")
            if not slug:
                continue
            index[canonical(name)] = slug
            index.setdefault(canonical(slug), slug)
            names[slug] = name
        self._index, self._names, self._loaded_at = index, names, time.time()
        return index

    def _ensure(self) -> dict:
        if self._index is None or (time.time() - self._loaded_at) > self.ttl:
            self.refresh()
        return self._index or {}

    # --- API pública ----------------------------------------------------------
    def workspace_name(self, folder_name: str) -> str:
        """Nombre del workspace en el servidor para una carpeta local (aplica alias)."""
        return self.aliases.get(folder_name, folder_name)

    def nombre_real(self, slug: str) -> str:
        return self._names.get(slug, slug)

    def slug(self, folder_name: str) -> tuple:
        """(slug, existe_en_servidor) para la carpeta local dada.

        Si no hay coincidencia devuelve la regla antigua con existe=False.
        """
        name = self.workspace_name(folder_name)
        try:
            index = self._ensure()
        except Exception:
            index = {}
        for key in (canonical(name), canonical(slug_naive(name))):
            if key and key in index:
                return index[key], True
        return slug_naive(name), False

    def lista(self) -> dict:
        """{slug: nombre} de todos los workspaces del servidor."""
        try:
            self._ensure()
        except Exception:
            return {}
        return dict(self._names)

    def crear(self, folder_name: str) -> str | None:
        """Crea el workspace para la carpeta local y devuelve su slug real."""
        name = self.workspace_name(folder_name)
        try:
            resp = requests.post(
                f"{self.base_url}/api/v1/workspace/new",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"name": name},
                timeout=20,
            )
            if resp.status_code in (200, 201):
                data = resp.json().get("workspace") or {}
                if isinstance(data, list):
                    data = data[0] if data else {}
                slug = (data.get("slug") if isinstance(data, dict) else None) or slug_naive(name)
                self._index = None  # fuerza recarga en la próxima consulta
                return slug
        except Exception:
            return None
        return None
