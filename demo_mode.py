"""Modo demo: el prospecto de una demo de InfoHub carga sus documentos.

InfoHub crea los workspaces de la demo según el tipo de empresa. Al elegir
una carpeta base, el panel crea dentro una subcarpeta por workspace; al
sincronizar, sube lo nuevo y quita de InfoHub lo que se borró de la carpeta.

Todo va con la sesión del usuario de la demo (JWT de /api/request-token),
nunca con la API key de administrador:
  - GET    /api/demo/mia                          workspaces, documentos y cuota
  - POST   /api/workspace/{slug}/upload-and-embed sube y procesa; gasta cupo
  - DELETE /api/demo/documentos/{docId}           quita y devuelve el cupo

La cuota es una sola para toda la demo. InfoHub la vuelve a comprobar (413).
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from i18n import Translator

logger = logging.getLogger(__name__)

# Una subida no se reintenta: InfoHub sigue procesando tras un corte y
# reenviar duplicaría el documento y su cupo.
UPLOAD_TIMEOUT_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 20

# Caracteres que Windows no admite en un nombre de carpeta.
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Archivos del sistema o temporales de Office que no son documentos.
_IGNORED_NAMES = {"thumbs.db", "desktop.ini"}


# En la versión web (Docker) el panel corre en el servidor: «la carpeta del
# prospecto» sería una carpeta del servidor. Ahí el modo demo se apaga.
# El texto está en i18n.py («demo.desktopOnly»); se conserva el nombre en español.
DEMO_DESKTOP_ONLY = Translator()("demo.desktopOnly")


def demo_mode_enabled() -> bool:
    """False si DEMO_MODE=0 (lo fija la imagen Docker)."""
    return os.getenv("DEMO_MODE", "1").strip().lower() not in ("0", "false", "no", "off")


def folder_name(workspace_name: str) -> str:
    """Nombre de carpeta válido en Windows y Linux para un workspace."""
    cleaned = _INVALID_CHARS.sub("-", workspace_name or "").strip(" .")
    return cleaned or "workspace"


def is_document(path: Path) -> bool:
    name = path.name
    return not (
        name.startswith(".")
        or name.startswith("~$")
        or name.lower() in _IGNORED_NAMES
        or name.endswith(".image_description")
        or name.endswith(".image_description.txt")
    )


def days_left(expires_at: str | None) -> int:
    if not expires_at:
        return 0
    try:
        end = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return 0
    seconds = (end - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(-(-seconds // 86400)))


def format_mb(size: int, tr: Translator | None = None) -> str:
    """Tamaño legible: en KB por debajo de 1 MB, para que no se lea «0,0 MB»."""
    return (tr or Translator()).size(size)


def choose_folder(initial: str = "", title: str | None = None) -> str | None:
    """Diálogo nativo para elegir una carpeta: "" si se cancela, None si no hay selector.

    El panel corre en el equipo del prospecto (se abre en su navegador), así
    que el diálogo de tkinter aparece en su pantalla.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        logger.warning(f"Sin selector de carpetas (tkinter): {e}")
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            path = filedialog.askdirectory(
                parent=root,
                initialdir=initial or str(Path.home()),
                title=title or Translator()("demo.chooseFolderTitle"),
                mustexist=True,
            )
        finally:
            root.destroy()
        return path or ""
    except Exception as e:
        logger.warning(f"No se pudo abrir el selector de carpetas: {e}")
        return None


class DemoSync:
    """Sincroniza la carpeta del prospecto con los workspaces de su demo.

    `matcher` es el InfoHubFileManager: se reutilizan sus reglas para nombrar
    archivos (`Sub/informe.pdf` -> `Sub__informe.pdf`) y emparejarlos con los
    documentos de InfoHub (`_remote_base_matches`).
    """

    def __init__(self, base_url: str, token: str, matcher, tr: Translator | None = None):
        self.tr = tr or Translator()
        self.base_url = (base_url or "").rstrip("/")
        self.token = token
        self.matcher = matcher

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "accept": "application/json"}

    # --- servidor ---------------------------------------------------------------
    def fetch(self) -> dict | None:
        """La demo del usuario, o None si no tiene una (o InfoHub no tiene demos)."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/demo/mia",
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if resp.status_code != 200:
                return None
            return resp.json().get("demo")
        except Exception as e:
            logger.warning(f"No se pudo consultar la demo: {e}")
            return None

    def _remove(self, doc_id: str) -> tuple[bool, str]:
        try:
            resp = requests.delete(
                f"{self.base_url}/api/demo/documentos/{requests.utils.quote(doc_id, safe='')}",
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS * 3,
            )
            if resp.status_code == 200:
                return True, ""
            return False, self._error(resp)
        except Exception as e:
            return False, str(e)

    def _upload(self, slug: str, path: Path, remote: str) -> tuple[bool, str]:
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    f"{self.base_url}/api/workspace/{slug}/upload-and-embed",
                    headers=self._headers(),
                    files={"file": (remote, f)},
                    timeout=UPLOAD_TIMEOUT_SECONDS,
                )
            if resp.status_code == 200 and (resp.json() or {}).get("success"):
                return True, ""
            return False, self._error(resp)
        except requests.Timeout:
            return False, self.tr("demo.timeout")
        except Exception as e:
            return False, str(e)

    def _error(self, resp) -> str:
        try:
            message = (resp.json() or {}).get("error")
        except Exception:
            message = None
        return message or self.tr("demo.status", status=resp.status_code)

    # --- carpeta local ----------------------------------------------------------
    def ensure_folders(self, base: str, demo: dict) -> list[Path]:
        """Crea una subcarpeta por workspace de la demo; devuelve sus rutas."""
        root = Path(base)
        root.mkdir(parents=True, exist_ok=True)
        folders = []
        for workspace in demo.get("workspaces", []):
            folder = root / folder_name(workspace["name"])
            folder.mkdir(exist_ok=True)
            folders.append(folder)
        return folders

    def plan(self, base: str, demo: dict) -> dict:
        """Qué subir, qué quitar y qué no entra en el cupo, por workspace.

        {nombre: {slug, carpeta, a_subir: [(Path, rel, remote)], huerfanos:
        [{docId, nombre, bytes}], sin_cupo: [rel]}}
        """
        m = self.matcher
        root = Path(base)
        result = {}
        for workspace in demo.get("workspaces", []):
            folder = root / folder_name(workspace["name"])
            local = []
            if folder.is_dir():
                for path in sorted(folder.rglob("*")):
                    if path.is_file() and is_document(path):
                        rel = m._rel_path(path, folder)
                        local.append((path, rel, m._remote_name(rel)))
            docs = workspace.get("documents", [])
            bases = [Path(d.get("filename") or "").name.removesuffix(".json") for d in docs]
            a_subir = [
                item for item in local
                if not any(m._remote_base_matches(b, item[2]) for b in bases)
            ]
            huerfanos = [
                {"docId": d["docId"], "nombre": d.get("title") or b, "bytes": d.get("bytes") or 0}
                for d, b in zip(docs, bases)
                if not any(m._remote_base_matches(b, remote) for _, _, remote in local)
            ]
            result[workspace["name"]] = {
                "slug": workspace["slug"],
                "carpeta": str(folder),
                "a_subir": a_subir,
                "huerfanos": huerfanos,
                "sin_cupo": [],
            }

        # Cuota compartida: cuenta lo que liberan los huérfanos y reparte el
        # resto en orden. InfoHub tiene la última palabra (413).
        docs_left = demo["maxDocs"] - demo["usedDocs"]
        bytes_left = demo["maxBytes"] - demo["usedBytes"]
        for data in result.values():
            docs_left += len(data["huerfanos"])
            bytes_left += sum(h["bytes"] for h in data["huerfanos"])
        for data in result.values():
            entran = []
            for item in data["a_subir"]:
                size = item[0].stat().st_size
                if docs_left <= 0 or size > bytes_left:
                    data["sin_cupo"].append(item[1])
                    continue
                docs_left -= 1
                bytes_left -= size
                entran.append(item)
            data["a_subir"] = entran
        return result

    # --- operaciones del panel ----------------------------------------------------
    def simulate(self, base: str) -> dict:
        """Lo que haría Sincronizar, sin cambiar nada (formato de show_simulation)."""
        demo = self.fetch()
        if not demo:
            return {"status": "error", "message": self.tr("demo.readFailed")}
        if not base or not Path(base).is_dir():
            return {"status": "error", "message": self.tr("demo.chooseFirst")}
        plan = self.plan(base, demo)
        simulation = {
            name: {
                "nuevo": False,
                "huerfanos": [h["nombre"] for h in data["huerfanos"]],
                "a_subir": [rel for _, rel, _ in data["a_subir"]],
                "sin_cupo": data["sin_cupo"],
            }
            for name, data in plan.items()
        }
        quitaria = sum(len(d["huerfanos"]) for d in simulation.values())
        subiria = sum(len(d["a_subir"]) for d in simulation.values())
        sin_cupo = sum(len(d["sin_cupo"]) for d in simulation.values())
        message = self.tr("demo.simulation", deleted=quitaria, uploaded=subiria)
        if sin_cupo:
            message += self.tr("demo.simulationNoQuota", count=sin_cupo)
        return {
            "status": "success",
            "message": message,
            "simulation": simulation,
            "would_delete": quitaria,
            "would_upload": subiria,
        }

    def sync(self, base: str) -> dict:
        """Quita lo que ya no está en la carpeta y después sube lo nuevo."""
        demo = self.fetch()
        if not demo:
            return {"status": "error", "message": self.tr("demo.readFailed")}
        if not base or not Path(base).is_dir():
            return {"status": "error", "message": self.tr("demo.chooseFirst")}
        self.ensure_folders(base, demo)
        plan = self.plan(base, demo)

        deleted, uploaded, errors = 0, 0, []
        # Primero se quita: así se libera cupo para lo que se sube después.
        for name, data in plan.items():
            for huerfano in data["huerfanos"]:
                ok, error = self._remove(huerfano["docId"])
                if ok:
                    deleted += 1
                    logger.info(f"[demo] Quitado de '{name}': {huerfano['nombre']}")
                else:
                    errors.append(f"{huerfano['nombre']}: {error}")
        for name, data in plan.items():
            for path, rel, remote in data["a_subir"]:
                ok, error = self._upload(data["slug"], path, remote)
                if ok:
                    uploaded += 1
                    logger.info(f"[demo] Subido a '{name}': {rel}")
                else:
                    errors.append(f"{rel}: {error}")
        sin_cupo = [rel for data in plan.values() for rel in data["sin_cupo"]]

        message = self.tr("demo.syncResult", uploaded=uploaded, deleted=deleted)
        if sin_cupo:
            message += self.tr("demo.syncNoQuota", count=len(sin_cupo), names=", ".join(sin_cupo[:5]))
        if errors:
            message += self.tr("demo.syncErrors", count=len(errors), errors="; ".join(errors[:5]))
        return {
            "status": "warning" if errors or sin_cupo else "success",
            "message": message,
            "workspaces_processed": len(plan),
            "uploaded": uploaded,
            "deleted": deleted,
            "skipped": len(sin_cupo),
            "errors": errors,
            "sin_cupo": sin_cupo,
        }
