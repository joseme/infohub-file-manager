"""
InfoHub File Manager - Flet Web Dashboard
Panel de control para sincronizar archivos con AnythingLLM/InfoHub
"""

import os
import asyncio
import base64
import logging
import re
import threading
import time
import requests
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import flet as ft
from flet import Icons
import ui_theme as T
from dotenv import load_dotenv
from config_manager import ConfigManager, DEFAULTS, BASE_DIR
from workspace_map import WorkspaceResolver, slug_naive
import sync_guards
import features
import demo_mode
from demo_mode import DemoSync
import i18n
from i18n import Translator

# Load environment variables
# Anclado al dir del ejecutable, no al CWD: si no, doble click no lee el .env
load_dotenv(BASE_DIR / ".env")

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.getenv("LOG_FILE") or str(BASE_DIR / "infohub.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Public URL of the InfoHub ecosystem portal ("Inicio" button). Empty hides it.
PORTAL_URL = os.getenv("PORTAL_URL", "").strip()

# Retry policy for update-embeddings (openresty proxy returns 502/503/504 under load)
# Workspaces que el file manager no sincroniza ni limpia: se cargan aparte
# (piloto de Infohub Chat, scripts/cargar_workspace.py).
PROTECTED_WORKSPACES_DEFAULT = "tributacion, odoo17"
# Extensiones que InfoHub divide en un documento por hoja (fase 1 de Infohub Chat).
SPREADSHEET_PER_SHEET_EXTS = {".xlsx"}
EMBEDDINGS_MAX_RETRIES = 3
EMBEDDINGS_RETRY_STATUS_CODES = {502, 503, 504}
EMBEDDINGS_RETRY_BACKOFF_SECONDS = 5
# Lotes chicos: cada pedido debe terminar antes del corte del proxy (60 s en NPM).
EMBEDDINGS_BATCH_SIZE = 10
# Borrado: en producción LanceDB tarda varios segundos por documento.
DELETE_BATCH_SIZE = 20
DELETE_TIMEOUT_SECONDS = 120
# Tras un 502/504 o un tiempo agotado, InfoHub sigue procesando: se espera a que
# los documentos aparezcan registrados antes de reenviar (reenviar duplica filas).
EMBEDDINGS_POLL_SECONDS = 15
EMBEDDINGS_WAIT_SECONDS = 300
# Espera máxima a que Flutter confirme el cierre del login antes de abrir otro modal.
LOGIN_DISMISS_WAIT_SECONDS = 2


def _query_param(page: ft.Page, key: str) -> str:
    """Lee un parámetro de la query string de la página web ('' si no está)."""
    try:
        value = page.query.to_dict.get(key)
        if value:
            return str(value)
    except Exception:
        pass
    for raw in (page.route, page.url):
        try:
            values = parse_qs(urlparse(raw or "").query).get(key)
            if values:
                return values[0]
        except Exception:
            pass
    return ""


class InfoHubFileManager:
    """Manages file synchronization with AnythingLLM/InfoHub"""

    def __init__(self, config=None):
        if config:
            self.api_key = os.getenv("ANYTHINGLLM_API_KEY") or config.get("anythingllm_api_key", "")
            self.base_url = os.getenv("ANYTHINGLLM_BASE_URL") or config.get("anythingllm_base_url", "http://localhost:3000")
            self.ollama_url = os.getenv("OLLAMA_BASE_URL") or config.get("ollama_base_url", "http://localhost:11434")
            self.ollama_model = os.getenv("OLLAMA_MODEL") or config.get("ollama_model", "llava:latest")
            self.image_description_active = config.get("image_description_active", True)
            self.watched_root = os.getenv("WATCHED_FOLDERS_ROOT") or config.get("watched_folders_root", "")
            protected = os.getenv("PROTECTED_WORKSPACES") or config.get(
                "protected_workspaces", PROTECTED_WORKSPACES_DEFAULT
            )
        else:
            self.api_key = os.getenv("ANYTHINGLLM_API_KEY", "")
            self.base_url = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3000")
            self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self.ollama_model = os.getenv("OLLAMA_MODEL", "llava:latest")
            self.image_description_active = (
                os.getenv("IMAGE_DESCRIPTION_ACTIVATE", "true").lower() == "true"
            )
            self.watched_root = os.getenv("WATCHED_FOLDERS_ROOT", "")
            protected = os.getenv("PROTECTED_WORKSPACES") or PROTECTED_WORKSPACES_DEFAULT
        # Ya son slugs: se normalizan con la regla local, sin consultar el servidor
        # (el resolver todavía no existe y el constructor no debe hacer pedidos).
        self.protected_workspaces = {
            slug_naive(name.strip())
            for name in str(protected or "").split(",")
            if name.strip()
        }

        # Guardas del borrado de huérfanos (sync_guards.py). No están en el
        # diálogo de configuración: se ajustan a mano en config.json.
        cfg = config or {}
        self.umbral_borrado_pct = cfg.get("umbral_borrado_pct", sync_guards.UMBRAL_PCT_DEFECTO)
        self.minimo_borrado = cfg.get("minimo_borrado", sync_guards.MINIMO_DEFECTO)
        self.montajes_requeridos = cfg.get("montajes_requeridos", []) or []

        # Cache within a single operation to avoid duplicate server lookups
        # for the same workspace and to remember docpaths already uploaded.
        self._base_name_cache: dict[str, set[str]] = {}
        self._uploaded_docpaths: set[str] = set()

        # Textos de la sesión (i18n.py); la interfaz lo cambia al elegir idioma.
        self.tr = Translator()

        # None = sin filtro de usuario; tras login: {slug: nombre} habilitados.
        self.session_token: str = ""
        self.allowed_workspaces: dict[str, str] | None = None

        # Resuelve el slug real de cada workspace contra el servidor (perezoso).
        self._resolver: WorkspaceResolver | None = None

    def login(self, username: str, password: str) -> tuple[bool, str | None]:
        """Autentica contra InfoHub y guarda JWT + workspaces habilitados del usuario.

        Fail-closed: si la lista de workspaces no se puede obtener, el login
        falla en vez de caer a acceso sin restricción.
        """
        base = self.base_url.rstrip("/")
        try:
            resp = requests.post(
                f"{base}/api/request-token",
                json={"username": username, "password": password},
                headers={"accept": "application/json"},
                timeout=10,
            )
            data = resp.json()
            if resp.status_code != 200 or not data.get("valid"):
                return False, data.get("message") or self.tr("login.invalid")

            self.session_token = data.get("token") or ""
            allowed = self._fetch_allowed_workspaces()
            if allowed is None:
                self.session_token = ""
                return False, self.tr("result.noWorkspaces")
            self.allowed_workspaces = allowed
            return True, None
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False, self.tr("result.connection", error=e)

    def login_with_ticket(self, ticket: str) -> tuple[bool, str | None, str | None]:
        """SSO desde el portal de InfoHub: canjea un ticket de un solo uso.

        Devuelve (ok, mensaje_error, username).
        """
        base = self.base_url.rstrip("/")
        try:
            resp = requests.post(
                f"{base}/api/system/app-ticket/redeem",
                json={"ticket": ticket},
                headers={"accept": "application/json"},
                timeout=10,
            )
            data = resp.json()
            if resp.status_code != 200 or not data.get("valid") or not data.get("token"):
                return False, data.get("message") or "Ticket inválido o vencido", None

            self.session_token = data["token"]
            allowed = self._fetch_allowed_workspaces()
            if allowed is None:
                self.session_token = ""
                return False, self.tr("result.noWorkspaces"), None
            self.allowed_workspaces = allowed
            return True, None, (data.get("user") or {}).get("username")
        except Exception as e:
            logger.error(f"Ticket login error: {e}")
            return False, self.tr("result.connection", error=e), None

    def _fetch_allowed_workspaces(self) -> dict[str, str] | None:
        """{slug: nombre} visibles para el usuario logueado (server filtra por membresía)."""
        try:
            resp = requests.get(
                f"{self.base_url.rstrip('/')}/api/workspaces",
                headers={
                    "Authorization": f"Bearer {self.session_token}",
                    "accept": "application/json",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error(f"Error fetching user workspaces: {resp.status_code}")
                return None
            return {
                ws.get("slug"): ws.get("name") or ws.get("slug")
                for ws in resp.json().get("workspaces", [])
                if ws.get("slug")
            }
        except Exception as e:
            logger.error(f"Error fetching user workspaces: {e}")
            return None

    def scan_files(self) -> dict:
        """Scan watched folders for files"""
        if not self.watched_root:
            return {"status": "error", "message": self.tr("result.rootNotConfigured")}

        root_path = Path(self.watched_root)
        if not root_path.exists():
            return {
                "status": "error",
                "message": self.tr("result.rootMissing", path=self.watched_root),
            }

        workspaces = {}
        for item in root_path.iterdir():
            if item.is_dir() and (
                item.name.startswith("Infohub") or item.name.startswith("AnythingLLM")
            ):
                for workspace_folder in item.iterdir():
                    if workspace_folder.is_dir():
                        workspaces.setdefault(workspace_folder.name, {
                            "path": str(workspace_folder),
                            "file_count": 0,
                            "files": [],
                        })

        # Only include workspaces the API key can actually access
        accessible = self.get_accessible_workspace_names(list(workspaces.keys()))
        workspaces = {name: data for name, data in workspaces.items() if name in accessible}

        for ws_name, ws_data in workspaces.items():
            ws_path = Path(ws_data["path"])
            files = ws_path.rglob("*")
            file_names = [
                self._rel_path(f, ws_path) for f in files
                if f.is_file()
                and not f.name.endswith(".image_description")
                and not f.name.endswith(".image_description.txt")
            ]
            ws_data["file_count"] = len(file_names)
            ws_data["files"] = file_names

        total_files = sum(ws["file_count"] for ws in workspaces.values())

        return {
            "status": "success",
            "workspaces": workspaces,
            "total_workspaces": len(workspaces),
            "total_files": total_files,
        }

    def get_workspace_slug(self, workspace_name: str) -> str:
        """Slug real del workspace en el servidor para un nombre de carpeta.

        El servidor no sigue la regla local ('Tributación CR' es 'tributacion',
        'Legislación Seguros CR' es 'seguros-cr'), así que se consulta
        GET /api/v1/workspaces y se usa el slug real (con alias locales como
        odoo -> odoo17). Si el workspace no existe todavía, se devuelve la regla
        antigua para que create_workspace lo cree con ese slug.
        """
        try:
            if self._resolver is None:
                self._resolver = WorkspaceResolver(self.base_url, self.api_key)
            return self._resolver.slug(workspace_name)[0]
        except Exception as e:
            logger.warning(f"No se pudo resolver el slug de '{workspace_name}': {e}")
            return workspace_name.lower().replace(" ", "-").replace("_", "-")

    def is_protected(self, workspace_name: str) -> bool:
        """Workspace administrado fuera del file manager: no se sincroniza ni se limpia."""
        return self.get_workspace_slug(workspace_name) in self.protected_workspaces

    def _skip_protected(self, workspaces_by_name: dict) -> tuple[dict, list]:
        protegidos = sorted(n for n in workspaces_by_name if self.is_protected(n))
        for name in protegidos:
            logger.info(f"Workspace '{name}' protegido: se administra fuera del file manager")
        return (
            {n: f for n, f in workspaces_by_name.items() if n not in protegidos},
            protegidos,
        )

    def is_workspace_accessible(self, workspace_name: str) -> bool:
        """Return True if the current API key can access the workspace."""
        slug = self.get_workspace_slug(workspace_name)
        url = f"{self.base_url}/api/v1/workspace/{slug}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "accept": "application/json",
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                workspace = data.get("workspace")
                if isinstance(workspace, list) and len(workspace) > 0:
                    workspace = workspace[0]
                return isinstance(workspace, dict) and bool(workspace.get("slug"))
            return False
        except Exception:
            return False

    def get_accessible_workspace_names(self, folder_names: list) -> set:
        """Given local folder names, return only those accessible to the API key
        and permitted to the logged-in user."""
        accessible = set()
        for name in folder_names:
            if (
                self.allowed_workspaces is not None
                and self.get_workspace_slug(name) not in self.allowed_workspaces
            ):
                continue
            # Sin API key el chequeo /v1 siempre fallaría y ocultaría todo;
            # el alcance ya está limitado por allowed_workspaces.
            if not self.api_key or self.is_workspace_accessible(name):
                accessible.add(name)
        return accessible

    def get_workspace_documents(self, workspace_name: str) -> dict:
        """Get documents in a workspace.

        Returns:
            dict with:
                - "base_names": set of base filenames (for existence checks)
                - "doc_names": dict mapping base_name -> docpath ("carpeta/archivo.json"),
                  que es lo que espera /v1/system/remove-documents
                - "raw_docs": list of raw document dicts
        """
        try:
            slug = self.get_workspace_slug(workspace_name)
            url = f"{self.base_url}/api/v1/workspace/{slug}"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "accept": "application/json",
            }

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                documents = []
                # Navigate response structure
                if isinstance(data, dict):
                    workspace = data.get("workspace", [])
                    if isinstance(workspace, list):
                        if len(workspace) == 0:
                            return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": False}
                        workspace = workspace[0]
                    documents = (
                        workspace.get("documents", [])
                        if isinstance(workspace, dict)
                        else []
                    )
                elif isinstance(data, list) and len(data) > 0:
                    documents = (
                        data[0].get("documents", [])
                        if isinstance(data[0], dict)
                        else []
                    )

                base_names = set()
                doc_names = {}
                for doc in documents:
                    if isinstance(doc, dict):
                        docpath = doc.get("docpath", "")
                        if docpath:
                            filename = docpath.split("/")[-1]
                            base_name = filename.replace(".json", "")
                            base_names.add(base_name)
                            # remove-documents necesita la ruta con carpeta: con el
                            # nombre solo responde 200 sin borrar nada.
                            doc_names[base_name] = docpath

                return {
                    "base_names": base_names,
                    "doc_names": doc_names,
                    "raw_docs": documents,
                    "exists": True,
                }
            else:
                logger.warning(
                    f"Failed to get workspace documents: {response.status_code}"
                )
                return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": False}
        except Exception as e:
            logger.error(f"Error getting workspace documents: {e}")
            return {"base_names": set(), "doc_names": {}, "raw_docs": [], "exists": False}

    def create_workspace(self, name: str) -> bool:
        """Create a new workspace in AnythingLLM.

        Returns True if created, False if already exists or error.
        """
        try:
            url = f"{self.base_url}/api/v1/workspace/new"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "accept": "application/json",
            }
            payload = {"name": name}

            response = requests.post(url, headers=headers, json=payload, timeout=10)

            if response.status_code in (200, 201):
                logger.info(f"Created workspace '{name}'")
                return True

            # 400 usually means workspace already exists — that's fine
            if response.status_code == 400:
                logger.info(f"Workspace '{name}' already exists")
                return False

            logger.warning(f"Failed to create workspace '{name}': {response.status_code} - {response.text}")
            return False
        except Exception as e:
            logger.error(f"Error creating workspace '{name}': {e}")
            return False

    def _get_documents_area_docpaths(self, workspace_slug: str) -> list:
        """Find docpaths for a workspace in the documents area.

        This InfoHub instance stores uploaded files under documents/{slug}/
        (GET /api/v1/documents) but does not register them in the workspace
        listing until they are processed. Returns docpaths like
        "slug/filename.json" for embedding.
        """
        try:
            url = f"{self.base_url}/api/v1/documents"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "accept": "application/json",
            }

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning(f"Failed to get documents area: {response.status_code}")
                return []

            data = response.json()
            folders = data.get("localFiles", {}).get("items", [])
            for folder in folders:
                if isinstance(folder, dict) and folder.get("name") == workspace_slug:
                    return [
                        f"{workspace_slug}/{f['name']}"
                        for f in folder.get("items", [])
                        if isinstance(f, dict) and f.get("type") == "file" and f.get("name")
                    ]
            return []
        except Exception as e:
            logger.error(f"Error getting documents area for '{workspace_slug}': {e}")
            return []

    def _base_names_for(self, workspace_name: str, docs: dict = None) -> set:
        """Return all base names known for a workspace, using a per-operation
        cache so we do not query the server more than once per workspace."""
        if workspace_name in self._base_name_cache:
            return self._base_name_cache[workspace_name]

        if docs is None:
            docs = self.get_workspace_documents(workspace_name)
        slug = self.get_workspace_slug(workspace_name)
        base_names = set(docs.get("base_names", set()))
        for docpath in self._get_documents_area_docpaths(slug):
            base_names.add(docpath.split("/")[-1].replace(".json", ""))
        self._base_name_cache[workspace_name] = base_names
        return base_names

    # server slugifica nombres (espacios→'-', sin puntuación); esto iguala ambos lados
    _ACCENT_MAP = str.maketrans({
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n",
        "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
    })

    def _canonical_name(self, s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower().translate(self._ACCENT_MAP))

    def _base_name_matches(self, base: str, stem: str) -> bool:
        """Match stem local contra base_name del server comparando formas canónicas.

        El server guarda '{slugify(nombre)}-{uuid}.json' (report.pdf →
        report-<uuid>.json, 'Informe año.pdf' → 'Informe-ano.pdf-<uuid>.json'),
        así que la forma canónica de base arranca con la del stem.
        """
        if not stem:
            return base == stem
        # ponytail: match por prefijo canónico; un stem prefijo de otro archivo
        # ('Reporte', 'ReporteFinal') puede colisionar — separar por uuid si pasa.
        return self._canonical_name(base).startswith(self._canonical_name(stem))

    def _rel_path(self, file_path, workspace_folder) -> str:
        try:
            rel = file_path.relative_to(workspace_folder)
        except ValueError:
            rel = Path(file_path.name)
        return rel.as_posix()

    def _remote_name(self, rel_path) -> str:
        return rel_path.replace("/", "__")

    def _remote_stem(self, rel_path) -> str:
        return str(Path(self._remote_name(rel_path)).with_suffix(""))

    def _remote_base_matches(self, server_base: str, local_remote_name: str) -> bool:
        forms = {
            self._canonical_name(Path(local_remote_name).stem),
            self._canonical_name(local_remote_name),
        }
        if self._canonical_name(server_base) in forms:
            return True
        stripped = re.sub(
            r"([-.](?:[0-9a-fA-F]{6,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}))$",
            "",
            server_base,
        )
        if self._canonical_name(stripped) in forms:
            return True
        # InfoHub carga cada hoja de un .xlsx como un documento aparte:
        # 'planilla.xlsx' → 'planilla.xlsx-<hoja>-<uuid>.json'. La comparación
        # incluye la extensión, así que 'planilla.xlsx' no toma 'planilla2.xlsx-…'.
        if Path(local_remote_name).suffix.lower() in SPREADSHEET_PER_SHEET_EXTS:
            full = self._canonical_name(local_remote_name)
            return self._canonical_name(stripped).startswith(full) and len(
                self._canonical_name(stripped)
            ) > len(full)
        return False

    def _update_embeddings(self, workspace_name: str) -> bool:
        """Trigger embedding generation for all documents in a workspace.

        After uploading documents, this must be called so the vector DB
        is updated and queries can find the documents.

        Sends the pending documents in batches of EMBEDDINGS_BATCH_SIZE so each
        request ends before the reverse proxy's timeout. Never re-sends a
        document that is already registered: re-adding creates duplicate rows
        in workspace_documents.
        """
        try:
            slug = self.get_workspace_slug(workspace_name)
            docs = self.get_workspace_documents(workspace_name)
            if not docs.get("exists", False):
                logger.warning(f"Cannot update embeddings: workspace '{workspace_name}' not found")
                return False

            # Uploads on this InfoHub instance are not registered in the
            # workspace listing until processed — take them from the
            # documents area and keep only the unregistered ones.
            registered = self._registered_docpaths(docs)
            pending = [
                p for p in self._get_documents_area_docpaths(slug)
                if p not in registered
            ]
            if not pending:
                logger.info(f"No new documents to embed in workspace '{workspace_name}'")
                return True

            for i in range(0, len(pending), EMBEDDINGS_BATCH_SIZE):
                batch = pending[i:i + EMBEDDINGS_BATCH_SIZE]
                if not self._embed_batch(workspace_name, slug, batch):
                    return False
            logger.info(f"Embeddings updated for '{workspace_name}' ({len(pending)} docs)")
            return True
        except Exception as e:
            logger.error(f"Error updating embeddings for '{workspace_name}': {e}")
            return False

    @staticmethod
    def _registered_docpaths(docs: dict) -> set:
        return {
            doc["docpath"] for doc in docs.get("raw_docs", [])
            if isinstance(doc, dict) and doc.get("docpath")
        }

    def _still_unregistered(self, workspace_name: str, batch: list) -> list:
        registered = self._registered_docpaths(self.get_workspace_documents(workspace_name))
        return [p for p in batch if p not in registered]

    def _wait_until_registered(self, workspace_name: str, batch: list) -> list:
        """After a gateway timeout InfoHub keeps processing the request: wait
        for the batch to show up in the workspace instead of re-sending it.
        Returns the docpaths still unregistered when the wait is over."""
        pending = batch
        waited = 0
        while pending and waited < EMBEDDINGS_WAIT_SECONDS:
            time.sleep(EMBEDDINGS_POLL_SECONDS)
            waited += EMBEDDINGS_POLL_SECONDS
            pending = self._still_unregistered(workspace_name, pending)
        return pending

    def _embed_batch(self, workspace_name: str, slug: str, batch: list) -> bool:
        url = f"{self.base_url}/api/v1/workspace/{slug}/update-embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "accept": "application/json",
        }
        for attempt in range(EMBEDDINGS_MAX_RETRIES):
            # Did the request reach InfoHub, so it may still be processing it?
            maybe_processing = False
            try:
                response = requests.post(
                    url, headers=headers, json={"adds": batch, "deletes": []}, timeout=300
                )
            except requests.ReadTimeout as e:
                maybe_processing = True
                logger.warning(
                    f"Embeddings request timed out (attempt {attempt + 1}/{EMBEDDINGS_MAX_RETRIES}): {e}"
                )
            except requests.RequestException as e:
                logger.warning(
                    f"Embeddings request failed (attempt {attempt + 1}/{EMBEDDINGS_MAX_RETRIES}): {e}"
                )
            else:
                if response.status_code == 200:
                    return True
                if response.status_code not in EMBEDDINGS_RETRY_STATUS_CODES:
                    logger.warning(
                        f"Failed to update embeddings for '{workspace_name}': "
                        f"{response.status_code} - {response.text}"
                    )
                    return False
                # 502/504 come from the proxy: InfoHub may still be working.
                maybe_processing = response.status_code in (502, 504)
                logger.warning(
                    f"Embeddings update returned {response.status_code} "
                    f"(attempt {attempt + 1}/{EMBEDDINGS_MAX_RETRIES})"
                )

            if attempt == EMBEDDINGS_MAX_RETRIES - 1:
                break
            if maybe_processing:
                batch = self._wait_until_registered(workspace_name, batch)
            else:
                time.sleep(EMBEDDINGS_RETRY_BACKOFF_SECONDS * (attempt + 1))
                batch = self._still_unregistered(workspace_name, batch)
            if not batch:
                logger.info(f"Embeddings finished on the server for '{workspace_name}'")
                return True
            logger.info(f"Retrying {len(batch)} unregistered documents for '{workspace_name}'")

        logger.error(f"Error updating embeddings for '{workspace_name}': {len(batch)} documents left")
        return False

    def file_exists_in_workspace(
        self, file_path: Path, workspace_name: str, docs: dict = None,
        workspace_folder=None,
    ) -> bool:
        """Check if file already exists in workspace.

        Matches against the folder-qualified remote stem (Sub/informe.pdf →
        Sub__informe) so same-stem files in different subfolders don't collide.
        """
        rel = self._rel_path(file_path, workspace_folder or file_path.parent)
        return any(
            self._base_name_matches(base, self._remote_stem(rel))
            for base in self._base_names_for(workspace_name, docs)
        )

    def delete_documents(self, doc_names: list) -> tuple:
        """Delete documents from AnythingLLM system.

        Args:
            doc_names: docpaths con carpeta (e.g. ["ws/report.pdf-<uuid>.json"]).

        Borra en lotes de DELETE_BATCH_SIZE: en producción LanceDB tarda varios
        segundos por documento. Si un lote se corta por tiempo (o el proxy
        responde 502/504), comprueba qué sigue existiendo y solo cuenta como
        error lo que quedó.

        Returns:
            tuple: (success: bool, deleted_count: int, errors: list)
        """
        if not doc_names:
            return (True, 0, [])

        url = f"{self.base_url}/api/v1/system/remove-documents"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "accept": "application/json",
        }
        deleted = 0
        errors = []
        logger.info(f"Deleting {len(doc_names)} documents: {doc_names}")
        for i in range(0, len(doc_names), DELETE_BATCH_SIZE):
            batch = doc_names[i:i + DELETE_BATCH_SIZE]
            try:
                response = requests.delete(
                    url, headers=headers, json={"names": batch}, timeout=DELETE_TIMEOUT_SECONDS
                )
            except requests.ReadTimeout:
                response = None
            except Exception as e:
                logger.error(f"Error deleting documents: {e}")
                errors.append(str(e))
                continue

            if response is not None and response.status_code in (200, 201, 204):
                deleted += len(batch)
                continue
            if response is not None and response.status_code not in (502, 504):
                logger.warning(f"Failed to delete documents: {response.status_code} - {response.text}")
                errors.append(f"HTTP {response.status_code}: {response.text}")
                continue

            # Corte por tiempo: InfoHub puede haber borrado todo o parte.
            remaining = self._still_in_documents_area(batch)
            deleted += len(batch) - len(remaining)
            for name in remaining:
                errors.append(self.tr("result.deleteUnconfirmed", name=name))
            logger.warning(
                f"Delete batch timed out: {len(batch) - len(remaining)} borrados, {len(remaining)} pendientes"
            )

        if errors:
            return (False, deleted, errors)
        logger.info(f"Successfully deleted {deleted} documents")
        return (True, deleted, [])

    def _still_in_documents_area(self, docpaths: list) -> list:
        """Docpaths que todavía están en el área de documentos de InfoHub."""
        present = set()
        for folder in {p.split("/")[0] for p in docpaths}:
            present.update(self._get_documents_area_docpaths(folder))
        return [p for p in docpaths if p in present]

    def upload_file_to_workspace(
        self, file_path: Path, workspace_name: str,
        workspace_folder=None, skip_if_exists: bool = True, remote_name: str | None = None,
    ) -> tuple:
        """Upload a single file to AnythingLLM workspace

        remote_name: nombre con el que se sube en el servidor; por defecto el
        nombre calificado por carpeta ('Sub/informe.pdf' -> 'Sub__informe.pdf').

        Returns:
            tuple: (success: bool, skipped: bool, message: str)
        """
        try:
            # Folder-qualified remote identity so same-stem files in different
            # subfolders don't collide (Sub/informe.pdf → Sub__informe.pdf).
            rel = self._rel_path(file_path, workspace_folder or file_path.parent)
            remote = remote_name or self._remote_name(rel)

            # Auto-create workspace if missing + check file existence
            docs = self.get_workspace_documents(workspace_name)
            if not docs.get("exists", True):
                self.create_workspace(workspace_name)
                docs = self.get_workspace_documents(workspace_name)

            # Also guard against uploading twice in the same operation
            cache_key = f"{workspace_name}:{remote}"
            if cache_key in self._uploaded_docpaths:
                logger.info(f"Skipped {file_path.name} - already uploaded in this run")
                return (False, True, "already exists")

            if skip_if_exists and self.file_exists_in_workspace(
                file_path, workspace_name, docs, workspace_folder
            ):
                logger.info(f"Skipped {file_path.name} - already in {workspace_name}")
                return (False, True, "already exists")

            slug = self.get_workspace_slug(workspace_name)
            url = f"{self.base_url}/api/v1/document/upload/{slug}"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "accept": "application/json",
            }

            with open(file_path, "rb") as f:
                files = {"file": (remote, f)}
                response = requests.post(url, headers=headers, files=files, timeout=300)

            if response.status_code in (200, 201):
                logger.info(f"Uploaded {file_path.name} to {workspace_name}")
                self._uploaded_docpaths.add(cache_key)
                return (True, False, "uploaded")
            else:
                logger.error(
                    f"Failed to upload {file_path.name}: {response.status_code} - {response.text}"
                )
                return (False, False, f"failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Error uploading {file_path.name}: {e}")
            return (False, False, str(e))

    def sort_files(self) -> dict:
        """Sort files into appropriate workspaces and generate image descriptions"""
        try:
            # Clear operation caches so each run starts fresh
            self._base_name_cache.clear()
            self._uploaded_docpaths.clear()
            if not self.watched_root:
                return {
                    "status": "error",
                    "message": self.tr("result.rootNotConfigured"),
                }

            root_path = Path(self.watched_root)
            if not root_path.exists():
                return {
                    "status": "error",
                    "message": self.tr("result.rootMissing", path=self.watched_root),
                }

            uploaded = 0
            skipped = 0
            images_processed = 0
            images_skipped = 0
            image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

            # Deduplicate workspaces by name across parent dirs
            workspaces_by_name = {}
            for item in root_path.iterdir():
                if item.is_dir() and (
                    item.name.startswith("Infohub")
                    or item.name.startswith("AnythingLLM")
                ):
                    for workspace_folder in item.iterdir():
                        if workspace_folder.is_dir():
                            workspaces_by_name.setdefault(workspace_folder.name, workspace_folder)

            # Protected workspaces are managed outside the file manager.
            workspaces_by_name, protegidos = self._skip_protected(workspaces_by_name)

            # Only process workspaces the API key can access
            accessible = self.get_accessible_workspace_names(list(workspaces_by_name.keys()))
            workspaces_by_name = {
                name: folder for name, folder in workspaces_by_name.items() if name in accessible
            }

            for workspace_name, workspace_folder in workspaces_by_name.items():
                # Ensure remote workspace exists, even if folder is empty
                docs = self.get_workspace_documents(workspace_name)
                if not docs.get("exists", False):
                    self.create_workspace(workspace_name)

                for file_path in workspace_folder.rglob("*"):
                    if file_path.is_file() and not file_path.name.endswith(
                        ".image_description"
                    ) and not file_path.name.endswith(
                        ".image_description.txt"
                    ):
                        success, was_skipped, msg = self.upload_file_to_workspace(
                            file_path, workspace_name, workspace_folder=workspace_folder
                        )
                        if success:
                            uploaded += 1
                        elif was_skipped:
                            skipped += 1

                        if file_path.suffix.lower() in image_extensions:
                            desc_file = file_path.with_name(file_path.name + ".image_description.txt")
                            if self.image_description_active and not desc_file.exists():
                                try:
                                    description = self._generate_image_description(file_path)
                                    with open(desc_file, "w", encoding="utf-8") as f:
                                        f.write(description)
                                    images_processed += 1
                                    logger.info(f"Created description for {file_path.name}")
                                except Exception as img_err:
                                    logger.error(f"Error creating description for {file_path.name}: {img_err}")
                            elif desc_file.exists():
                                images_skipped += 1

                # Update embeddings for this workspace
                self._update_embeddings(workspace_name)

            message = self.tr("result.sorted", uploaded=uploaded, skipped=skipped,
                              described=images_processed, existing=images_skipped)
            if protegidos:
                message += self.tr("result.protected", names=", ".join(protegidos))
            return {
                "status": "success",
                "message": message,
                "uploaded": uploaded,
                "skipped": skipped,
                "images_processed": images_processed,
                "images_skipped": images_skipped,
                "protected": protegidos,
            }
        except Exception as e:
            logger.error(f"Error sorting files: {e}")
            return {"status": "error", "message": str(e)}

    def clean_folders(self) -> dict:
        """Clean empty folders in InfoHub"""
        return {"status": "success", "message": self.tr("result.emptyCleaned")}

    def simulate_clean(self) -> dict:
        """Simulación de la carga completa: qué se borraría y qué se subiría,
        sin cambiar nada en InfoHub."""
        return self.full_upload_and_clean(simular=True)

    def _motivo_bloqueo_borrado(self, carpeta, locales: int, remotos: int, huerfanos: int):
        """Motivo para no borrar los huérfanos de un workspace, o None (ver sync_guards)."""
        if sync_guards.montaje_caido(carpeta, self.montajes_requeridos):
            return self.tr("guard.unmounted")
        return sync_guards.evaluar_borrado(locales, remotos, huerfanos,
                                           umbral_pct=self.umbral_borrado_pct,
                                           minimo=self.minimo_borrado,
                                           tr=self.tr)

    def full_upload_and_clean(self, simular: bool = False) -> dict:
        """Full synchronization: upload new/updated files, delete removed ones.

        Con simular=True decide igual qué es huérfano y qué falta subir, pero no
        borra, no sube, no crea workspaces ni actualiza embeddings.
        """
        try:
            # Clear operation caches so each run starts fresh
            self._base_name_cache.clear()
            self._uploaded_docpaths.clear()
            if not self.watched_root:
                return {
                    "status": "error",
                    "message": self.tr("result.rootNotConfigured"),
                }

            root_path = Path(self.watched_root)
            if not root_path.exists():
                return {
                    "status": "error",
                    "message": self.tr("result.rootMissing", path=self.watched_root),
                }

            uploaded = 0
            skipped = 0
            deleted = 0
            delete_errors = []
            workspaces_processed = 0
            plan = {}
            problema = sync_guards.raiz_accesible(root_path, tr=self.tr)
            if problema:
                return {"status": "error", "message": problema}
            estado_fuentes = sync_guards.cargar_estado_fuentes()
            bloqueados = {}

            # Deduplicate workspaces by name across parent dirs
            workspaces_by_name = {}
            for item in root_path.iterdir():
                if item.is_dir() and (
                    item.name.startswith("Infohub")
                    or item.name.startswith("AnythingLLM")
                ):
                    for workspace_folder in item.iterdir():
                        if workspace_folder.is_dir():
                            workspaces_by_name.setdefault(workspace_folder.name, workspace_folder)

            # Protected workspaces are managed outside the file manager.
            workspaces_by_name, protegidos = self._skip_protected(workspaces_by_name)

            # Only process workspaces the API key can access
            accessible = self.get_accessible_workspace_names(list(workspaces_by_name.keys()))
            workspaces_by_name = {
                name: folder for name, folder in workspaces_by_name.items() if name in accessible
            }

            for workspace_name, workspace_folder in workspaces_by_name.items():
                workspaces_processed += 1

                # --- Step 1: Collect local files (folder-qualified remote names) ---
                collection_failed = False
                archivos = []
                try:
                    archivos = [
                        f for f in workspace_folder.rglob("*")
                        if f.is_file()
                        and not f.name.endswith(".image_description")
                        and not f.name.endswith(".image_description.txt")
                    ]
                except Exception:
                    collection_failed = True
                local_remote_names = {
                    self._remote_name(self._rel_path(f, workspace_folder))
                    for f in archivos
                }

                # --- Step 2: Find and delete orphaned remote documents ---
                docs_info = self.get_workspace_documents(workspace_name)
                if not docs_info.get("exists", False):
                    if simular:
                        plan[workspace_name] = {
                            "nuevo": True,
                            "huerfanos": [],
                            "a_subir": sorted(self._rel_path(f, workspace_folder) for f in archivos),
                        }
                        continue
                    self.create_workspace(workspace_name)
                    docs_info = self.get_workspace_documents(workspace_name)
                remote_base_names = docs_info["base_names"]
                doc_names_map = docs_info["doc_names"]

                if collection_failed:
                    orphaned = []
                else:
                    huerfanos_base = [
                        b
                        for b in remote_base_names
                        if b in doc_names_map
                        and not any(
                            self._remote_base_matches(b, n)
                            for n in local_remote_names
                        )
                    ]
                    # lo subido por fuentes externas (SharePoint, Zoho...) no tiene copia local
                    if huerfanos_base and estado_fuentes:
                        externos = sync_guards.nombres_externos(
                            self.get_workspace_slug(workspace_name), estado_fuentes)
                        huerfanos_base = sync_guards.quitar_externos(
                            huerfanos_base, externos, self._remote_base_matches)
                    orphaned = [doc_names_map[b] for b in huerfanos_base]

                bloqueo = None
                if orphaned:
                    bloqueo = self._motivo_bloqueo_borrado(
                        workspace_folder, len(archivos), len(remote_base_names), len(orphaned))
                    if bloqueo:
                        bloqueados[workspace_name] = bloqueo
                        logger.warning(
                            f"Borrado de huérfanos BLOQUEADO en '{workspace_name}': {bloqueo}")

                if simular:
                    a_subir = sorted(
                        self._rel_path(f, workspace_folder) for f in archivos
                        if not self.file_exists_in_workspace(f, workspace_name, docs_info, workspace_folder)
                    )
                    plan[workspace_name] = {
                        "nuevo": False,
                        "huerfanos": sorted(orphaned),
                        "a_subir": a_subir,
                        "sin_lista_local": collection_failed,
                        "borrado_bloqueado": bloqueo,
                    }
                    if not bloqueo:
                        for doc_name in orphaned:
                            logger.info(f"[simulación] Se borraría de '{workspace_name}': {doc_name}")
                    continue

                if orphaned and not bloqueo:
                    logger.info(
                        f"Orphaned documents in '{workspace_name}': {orphaned}"
                    )
                    success, count, errs = self.delete_documents(orphaned)
                    # Cuenta lo que de verdad se borró, aunque el lote fallara a medias.
                    deleted += count
                    if success:
                        for doc_name in orphaned:
                            logger.info(f"Deleted orphaned document: {doc_name}")
                    else:
                        delete_errors.extend(errs)

                # --- Step 3: Upload local files ---
                for file_path in archivos:
                    success, was_skipped, msg = self.upload_file_to_workspace(
                        file_path, workspace_name,
                        workspace_folder=workspace_folder,
                    )
                    if success:
                        uploaded += 1
                    elif was_skipped:
                        skipped += 1

                # --- Step 4: Update embeddings ---
                self._update_embeddings(workspace_name)

            if simular:
                permitidos = [p for p in plan.values() if not p.get("borrado_bloqueado")]
                borrarian = sum(len(p["huerfanos"]) for p in permitidos)
                subirian = sum(len(p["a_subir"]) for p in plan.values())
                con_huerfanos = sum(1 for p in permitidos if p["huerfanos"])
                message = self.tr("result.simulation", deleted=borrarian, workspaces=con_huerfanos,
                                  uploaded=subirian, checked=workspaces_processed)
                if protegidos:
                    message += self.tr("result.protected", names=", ".join(protegidos))
                if bloqueados:
                    message += self.tr("result.blocked", count=len(bloqueados), names=", ".join(bloqueados))
                return {
                    "status": "success",
                    "message": message,
                    "blocked_deletions": bloqueados,
                    "simulation": plan,
                    "would_delete": borrarian,
                    "would_upload": subirian,
                    "workspaces_processed": workspaces_processed,
                    "protected": protegidos,
                }

            result_msg = self.tr("result.full", processed=workspaces_processed, uploaded=uploaded,
                                 skipped=skipped, deleted=deleted)
            if delete_errors:
                result_msg += self.tr("result.fullDeleteErrors", count=len(delete_errors))
            if protegidos:
                result_msg += self.tr("result.fullProtected", names=", ".join(protegidos))
            if bloqueados:
                result_msg += self.tr("result.fullBlocked", count=len(bloqueados),
                                      details="; ".join(f"{n} ({m})" for n, m in bloqueados.items()))

            result = {
                "status": "success" if not (delete_errors or bloqueados) else "warning",
                "message": result_msg,
                "blocked_deletions": bloqueados,
                "workspaces_processed": workspaces_processed,
                "uploaded": uploaded,
                "skipped": skipped,
                "deleted": deleted,
                "protected": protegidos,
            }
            if delete_errors:
                result["delete_errors"] = delete_errors

            return result
        except Exception as e:
            logger.error(f"Error in full upload: {e}")
            return {"status": "error", "message": str(e)}

    def _generate_image_description(self, image_path: Path) -> str:
        """Generate a description via local Ollama API.

        Sends the image as base64 to the local Ollama endpoint using the
        HTTP API directly, avoiding local CLI/SDK timeout issues.
        """
        # Read and encode image to base64
        with open(image_path, "rb") as img_file:
            img_b64 = base64.b64encode(img_file.read()).decode("utf-8")

        url = f"{self.ollama_url}/api/chat"
        headers = {
            "Content-Type": "application/json",
        }
        # Only add Authorization header if an API key is configured (cloud endpoints)
        api_key = os.getenv("OLLAMA_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": self.ollama_model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": "Describe esta imagen de forma detallada y precisa. Incluye objetos, colores, escena, personas, texto visible y cualquier otro elemento relevante.",
                    "images": [img_b64],
                }
            ],
        }

        logger.info(f"Sending {image_path.name} to Ollama Cloud ({self.ollama_model})...")
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()

        description = data.get("message", {}).get("content", "").strip()
        if not description:
            raise RuntimeError("Ollama Cloud returned an empty description.")

        return description

    def create_image_descriptions(self) -> dict:
        """Generate AI descriptions for all images using Ollama Cloud"""
        if not self.image_description_active:
            return {
                "status": "warning",
                "message": self.tr("result.imagesDisabled"),
            }

        if not self.watched_root:
            return {
                "status": "error",
                "message": self.tr("result.rootNotConfigured"),
            }

        root_path = Path(self.watched_root)
        if not root_path.exists():
            return {
                "status": "error",
                "message": self.tr("result.rootMissing", path=self.watched_root),
            }

        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
        processed = 0
        skipped = 0
        errors = []

        # Collect all images first for better logging
        # Deduplicate workspaces by name across parent dirs
        images_to_process = []
        workspaces_by_name = {}
        for item in root_path.iterdir():
            if item.is_dir() and (
                item.name.startswith("Infohub")
                or item.name.startswith("AnythingLLM")
            ):
                for workspace_folder in item.iterdir():
                    if workspace_folder.is_dir():
                        workspaces_by_name.setdefault(workspace_folder.name, workspace_folder)

        for workspace_name, workspace_folder in workspaces_by_name.items():
            for file_path in workspace_folder.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                    desc_file = file_path.with_name(file_path.name + ".image_description.txt")
                    if desc_file.exists():
                        skipped += 1
                    else:
                        images_to_process.append(file_path)

        total_images = len(images_to_process) + skipped
        logger.info(f"Found {total_images} images: {len(images_to_process)} to process, {skipped} already have descriptions")

        if not images_to_process:
            return {
                "status": "success",
                "message": self.tr("result.imagesAllDone", count=skipped),
                "processed": 0,
                "skipped": skipped,
            }

        for idx, file_path in enumerate(images_to_process, 1):
            desc_file = file_path.with_name(file_path.name + ".image_description.txt")
            logger.info(f"[{idx}/{len(images_to_process)}] Processing {file_path.name}...")

            try:
                description = self._generate_image_description(file_path)

                with open(desc_file, "w", encoding="utf-8") as f:
                    f.write(description)

                logger.info(f"[{idx}/{len(images_to_process)}] Created description for {file_path.name}")
                processed += 1

            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}")
                errors.append(f"{file_path.name}: {str(e)}")

        if errors:
            return {
                "status": "warning" if processed > 0 else "error",
                "message": self.tr("result.imagesErrors", processed=processed, skipped=skipped, errors=len(errors)),
                "processed": processed,
                "skipped": skipped,
                "errors": errors,
            }

        return {
            "status": "success",
            "message": self.tr("result.imagesDone", processed=processed, skipped=skipped),
            "processed": processed,
            "skipped": skipped,
        }


async def _read_pref(page: ft.Page, key: str):
    """Preferencia del usuario (localStorage en web, preferencias locales en escritorio)."""
    try:
        return await page.shared_preferences.get(key)
    except Exception as e:
        logger.warning(f"No se pudo leer la preferencia {key}: {e}")
        return None


async def _write_pref(page: ft.Page, key: str, value: str):
    try:
        await page.shared_preferences.set(key, value)
    except Exception as e:
        logger.warning(f"No se pudo guardar la preferencia {key}: {e}")


async def main(page: ft.Page):
    # Lo que sobrevive a un cambio de idioma: la pantalla se vuelve a armar
    # (_build) con la misma sesión, sin cerrar la sesión de InfoHub.
    session = {
        "first": True,
        "user_lang": i18n.normalize(await _read_pref(page, i18n.PREF_LANGUAGE)),
        "instance_lang": i18n.normalize(await _read_pref(page, i18n.PREF_INSTANCE_LANGUAGE)),
        "config": None,
        "manager": None,
        "logs": [],
        "stats": {"workspaces": "0", "files": "0", "uploaded": "0", "pending": "0"},
        "demo": None,
        "busy": False,
    }
    _build_safely(page, session)


def _build_safely(page: ft.Page, session: dict):
    try:
        _build(page, session)
    except Exception as e:
        import traceback
        traceback.print_exc()
        page.add(ft.Column([
            ft.Text(f"Error: {e}", color=T.DANGER, size=17),
        ]))
        page.update()


def _rebuild(page: ft.Page, session: dict):
    """Vuelve a armar la pantalla (cambio de idioma) conservando la sesión."""
    while page.pop_dialog():
        pass
    page.overlay.clear()
    page.controls.clear()
    page.appbar = None
    _build_safely(page, session)
    page.update()


def _build(page: ft.Page, session: dict):
    first_build = session["first"]
    session["first"] = False
    tr = Translator(i18n.resolve(session["user_lang"], session["instance_lang"]))

    # ========== PAGE CONFIGURATION ==========
    if session["config"] is None:
        session["config"] = ConfigManager()
    config = session["config"]
    page.title = config.get("app_title", "InfoHub File Manager")
    page.theme_mode = ft.ThemeMode.LIGHT
    page.fonts = T.FONTS
    page.padding = 0
    page.spacing = 0
    page.bgcolor = T.BG_PRIMARY

    # Marca InfoHub (manual KnowHub v1.0): tokens en ui_theme.py
    page.theme = T.page_theme()

    if session["manager"] is None:
        session["manager"] = InfoHubFileManager(config)
    manager = session["manager"]
    manager.tr = tr

    # ========== IDIOMA ==========
    def change_language(lang):
        lang = i18n.normalize(lang)
        if not lang or lang == tr.lang:
            return
        if session["busy"]:
            show_snackbar(tr("ops.busy"), T.WARN_DEEP)
            return
        session["user_lang"] = lang
        page.run_task(_write_pref, page, i18n.PREF_LANGUAGE, lang)
        _rebuild(page, session)

    def language_dropdown():
        return T.dropdown(
            value=tr.lang,
            options=[ft.dropdown.Option(key=lang, text=i18n.ENDONYMS[lang]) for lang in i18n.SUPPORTED],
            dense=True,
            text_size=13,
            width=130,
            content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=6),
            tooltip=tr("common.language"),
            on_select=lambda e: change_language(e.control.value),
        )

    def apply_instance_language(lang, rebuild=True):
        """Corre en un hilo. Guarda el idioma de la instancia; si cambia el de la
        pantalla (el usuario no eligió uno), la vuelve a armar."""
        lang = i18n.normalize(lang)
        if not lang or lang == session["instance_lang"]:
            return False
        session["instance_lang"] = lang
        page.run_task(_write_pref, page, i18n.PREF_INSTANCE_LANGUAGE, lang)
        changed = i18n.resolve(session["user_lang"], lang) != tr.lang
        if changed and rebuild:
            async def _do():
                if not session["busy"]:
                    _rebuild(page, session)
            page.run_task(_do)
        return changed

    # ========== LOGIN DIALOG ==========
    login_base_url = T.textfield(
        label=tr("login.url"),
        value=manager.base_url or "http://localhost:3001",
        dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
        text_size=13,
        width=360,
    )
    login_username = T.textfield(
        label=tr("login.username"),
        dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
        text_size=13,
        width=360,
    )
    login_password = T.textfield(
        label=tr("login.password"),
        password=True,
        can_reveal_password=True,
        dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
        text_size=13,
        width=360,
        on_submit=lambda e: _handle_login(),
    )
    login_error = ft.Text("", color=T.DANGER, size=13)
    if config.last_error:
        login_error.value = tr("login.badConfig", error=config.last_error)
        login_error.color = T.WARN
    login_progress = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)
    login_dialog = ft.AlertDialog(
        modal=True,
        bgcolor=T.BG_SECONDARY,
        title=ft.Row(
            [
                ft.Icon(Icons.LOCK_OUTLINED, color=T.ACCENT_HOVER),
                ft.Text(tr("login.title"), size=18, weight=ft.FontWeight.BOLD, color=T.TEXT, expand=True),
                language_dropdown(),
            ],
            spacing=8,
        ),
        content=ft.Column(
            [
                ft.Text(tr("login.intro"), size=13, color=T.TEXT_2),
                ft.Container(height=8),
                login_base_url,
                login_username,
                login_password,
                ft.Row([login_error, login_progress], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ],
            spacing=10,
            tight=True,
        ),
        actions=[
            ft.TextButton(
                tr("login.backHome") if PORTAL_URL else tr("login.exit"),
                icon=Icons.HOME_OUTLINED if PORTAL_URL else Icons.CLOSE_OUTLINED,
                on_click=lambda e: go_to_portal() if PORTAL_URL else page.window.close(),
            ),
            ft.FilledButton(
                tr("login.submit"),
                icon=Icons.LOGIN_OUTLINED,
                on_click=lambda e: _handle_login(),
                style=ft.ButtonStyle(
                    bgcolor=T.ACCENT,
                    color=T.ON_ACCENT,
                    shape=T.SHAPE,
                ),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    # ========== DIÁLOGO WORKSPACES HABILITADOS ==========
    user_ws_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
    user_ws_dialog = ft.AlertDialog(
        modal=True,
        bgcolor=T.BG_SECONDARY,
        title=ft.Row(
            [
                ft.Icon(Icons.FOLDER_SPECIAL_OUTLINED, color=T.ACCENT_HOVER),
                ft.Text(tr("workspaces.title"), size=18, weight=ft.FontWeight.BOLD, color=T.TEXT),
            ],
            spacing=8,
        ),
        content=ft.Container(content=user_ws_list, width=380, height=300),
        actions=[
            ft.FilledButton(
                tr("common.accept"),
                icon=Icons.CHECK_OUTLINED,
                on_click=lambda e: page.pop_dialog(),
                style=ft.ButtonStyle(
                    bgcolor=T.ACCENT,
                    color=T.ON_ACCENT,
                    shape=T.SHAPE,
                ),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    def _show_user_workspaces():
        allowed = manager.allowed_workspaces or {}
        if allowed:
            user_ws_list.controls = [
                ft.Row(
                    [
                        ft.Icon(Icons.FOLDER_OUTLINED, color=T.ACCENT_HOVER, size=18),
                        ft.Text(name, size=14, expand=True),
                        ft.Text(slug, size=11, color=T.TEXT_3),
                    ],
                    spacing=8,
                )
                for slug, name in allowed.items()
            ]
        else:
            user_ws_list.controls = [
                ft.Text(
                    tr("workspaces.none"),
                    size=14,
                    color=T.TEXT_2,
                    italic=True,
                )
            ]
        page.show_dialog(user_ws_dialog)

    def _validate_credentials(base_url: str, api_key: str) -> bool:
        try:
            url = f"{base_url.rstrip('/')}/api/v1/auth"
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {api_key}", "accept": "application/json"},
                timeout=10,
            )
            return response.status_code == 200
        except Exception:
            return False

    # La lista de workspaces se abre recién cuando Flutter confirma que cerró el
    # login: dos modales encimados durante la animación de cierre dejan el login
    # pegado en pantalla.
    pending_workspaces = {"show": False}

    def _show_pending_workspaces(e=None):
        if pending_workspaces["show"]:
            pending_workspaces["show"] = False
            _show_user_workspaces()

    login_dialog.on_dismiss = _show_pending_workspaces

    def _after_login(username: str, base_url: str, close_login: bool = False):
        """Corre en un hilo: valida la API key y deja la UI al bucle de Flet.

        Un usuario de demo de InfoHub entra en modo demo: trabaja solo con su
        sesión y no necesita la API key.
        """
        # Otra URL puede ser otra instancia, con otro idioma.
        relang = apply_instance_language(i18n.fetch_instance_language(base_url), rebuild=False)
        demo = DemoSync(base_url, manager.session_token, manager, tr).fetch() if manager.session_token else None
        if demo and not demo_mode.demo_mode_enabled():
            # Versión web: un prospecto no opera sobre carpetas del servidor.
            manager.session_token = ""
            manager.allowed_workspaces = None
            logger.warning(f"Usuario de demo rechazado en la versión web: {username}")
            page.run_task(_show_login_error, tr("demo.desktopOnly"), not close_login)
            return
        api_ok = demo is not None or (bool(manager.api_key) and _validate_credentials(base_url, manager.api_key))
        page.run_task(_finish_login, username, api_ok, close_login, demo, relang)

    async def _finish_login(username: str, api_ok: bool, close_login: bool, demo: dict | None = None,
                            relang: bool = False):
        # Los diálogos se tocan solo desde el bucle de la sesión: desde un hilo
        # el parche open=False del login puede perderse y el modal no se cierra.
        show_snackbar(tr("login.signedIn", user=username), T.OK_DEEP)
        add_log(tr("login.signedInLog", user=username, count=len(manager.allowed_workspaces or {})), "success")
        if relang:
            # La instancia está en otro idioma: se rearma la pantalla ya con la
            # sesión iniciada (repone el modo demo si corresponde).
            session["demo"] = demo
            _rebuild(page, session)
            return
        if demo:
            enter_demo_mode(demo)
            if close_login:
                login_error.value = ""
                login_progress.visible = False
                page.pop_dialog()
            return
        if not api_ok:
            show_snackbar(tr("login.noApiKey"), T.DANGER)
            add_log(tr("login.noApiKeyLog"), "warning")
        if not close_login:
            _show_user_workspaces()
            return
        login_error.value = ""
        login_progress.visible = False
        pending_workspaces["show"] = True
        page.pop_dialog()
        await asyncio.sleep(LOGIN_DISMISS_WAIT_SECONDS)
        _show_pending_workspaces()  # Flutter no confirmó el cierre a tiempo

    async def _show_login_error(message: str, reopen: bool = False):
        login_error.value = message
        login_progress.visible = False
        if reopen:
            page.show_dialog(login_dialog)
        else:
            page.update()

    def _handle_ticket_login(ticket: str):
        """SSO desde el portal: sin ticket válido se cae al diálogo de login."""
        def _do():
            ok, msg, username = manager.login_with_ticket(ticket)
            page.run_task(page.push_route, "/")  # quita el ticket de la URL (seguro desde un hilo)
            if ok:
                _after_login(username or tr("common.user"), manager.base_url)
            else:
                add_log(tr("login.ssoFailedLog", error=msg), "warning")
                page.run_task(_show_login_error, tr("login.ssoFailed"), True)

        threading.Thread(target=_do, daemon=True).start()

    def go_to_portal():
        page.run_task(
            ft.UrlLauncher().launch_url, PORTAL_URL, web_only_window_name="_self"
        )

    def _handle_login():
        base_url = login_base_url.value.strip()
        username = login_username.value.strip()
        password = login_password.value or ""
        if not base_url or not username or not password:
            login_error.value = tr("login.required")
            page.update()
            return

        login_error.value = ""
        login_progress.visible = True
        page.update()
        logger.info(f"Intento de login: {base_url} (usuario: {username})")

        def _do_login():
            try:
                manager.base_url = base_url
                ok, msg = manager.login(username, password)
                logger.info(f"Resultado de login en {base_url}: ok={ok} mensaje={msg}")
                if not ok:
                    page.run_task(_show_login_error, msg or tr("login.invalid"))
                    return

                config.set("anythingllm_base_url", base_url)
                config.save()
                _after_login(username, base_url, close_login=True)
            except Exception as ex:
                logger.exception(f"Error inesperado en login: {ex}")
                page.run_task(_show_login_error, tr("common.error", error=ex))

        threading.Thread(target=_do_login, daemon=True).start()

    # Al rearmar la pantalla con la sesión iniciada, no se vuelve a pedir el login.
    signed_in = bool(manager.session_token)
    sso_ticket = _query_param(page, "ticket") if first_build else ""
    if not sso_ticket and not signed_in:
        page.show_dialog(login_dialog)

    # ========== STATE ==========
    is_processing = False

    # ========== UI COMPONENTS ==========

    # --- SnackBar for notifications ---
    # El mismo aviso sirve a todas las versiones de la pantalla: al cambiar de
    # idioma se cierra el abierto en lugar de dejar uno huérfano en el otro idioma.
    snackbar = session.get("snackbar")
    if snackbar is None:
        snackbar = ft.SnackBar(
            content=ft.Text("", color=T.ON_POPUP),
            action=ft.SnackBarAction(label=""),
            bgcolor=T.BG_POPUP,
            duration=4000,
        )
        snackbar.action.on_click = lambda e: setattr(snackbar, "open", False)
        session["snackbar"] = snackbar
    snackbar.action.label = tr("common.close")
    snackbar.open = False
    page.overlay.append(snackbar)

    def show_snackbar(message, color=T.BG_POPUP):
        snackbar.content.value = message
        snackbar.bgcolor = color
        snackbar.open = True
        page.update()

    # --- Stats Cards ---
    def create_stat_card(value, label, icon, color):
        return T.card(
            ft.Row(
                [
                    ft.Container(
                        content=ft.Icon(icon, color=color, size=22),
                        bgcolor=T.BG_PRIMARY,
                        border_radius=T.RADIUS,
                        padding=10,
                        width=44,
                        height=44,
                        alignment=ft.alignment.Alignment(0, 0),
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                str(value),
                                size=24,
                                weight=ft.FontWeight.BOLD,
                                color=T.TEXT,
                            ),
                            ft.Text(
                                label,
                                size=13,
                                color=T.TEXT_2,
                                weight=ft.FontWeight.W_500,
                            ),
                        ],
                        spacing=2,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                ],
                spacing=15,
                alignment=ft.MainAxisAlignment.START,
            ),
            col={"xs": 6, "sm": 6, "md": 3, "lg": 3, "xl": 3},
        )

    stats = session["stats"]
    workspaces_stat = create_stat_card(stats["workspaces"], tr("stats.workspaces"), Icons.FOLDER_COPY_OUTLINED, T.ACCENT)
    files_stat = create_stat_card(stats["files"], tr("stats.files"), Icons.DESCRIPTION_OUTLINED, T.TEAL)
    uploaded_stat = create_stat_card(stats["uploaded"], tr("stats.uploaded"), Icons.CLOUD_UPLOAD_OUTLINED, T.OK_DEEP)
    pending_stat = create_stat_card(stats["pending"], tr("stats.pending"), Icons.SCHEDULE_OUTLINED, T.WARN_DEEP)
    stat_cards = {"workspaces": workspaces_stat, "files": files_stat, "uploaded": uploaded_stat, "pending": pending_stat}

    def set_stat(name, value):
        """Actualiza un total y lo recuerda en la sesión (sobrevive al cambio de idioma)."""
        stats[name] = str(value)
        stat_cards[name].content.content.controls[1].controls[0].value = stats[name]

    def update_stats(result=None):
        if not result or result.get("status") not in ("success", "warning"):
            return

        # Scan results: workspaces & file counts
        if "total_workspaces" in result:
            set_stat("workspaces", result.get("total_workspaces", 0))
        if "total_files" in result:
            set_stat("files", result.get("total_files", 0))

        # Upload results: uploaded file count
        if "uploaded" in result:
            set_stat("uploaded", result.get("uploaded", 0))

        # Image description results: processed count
        if "processed" in result:
            set_stat("uploaded", result.get("processed", 0))

        # Pending: skipped uploads or images still needing descriptions
        skipped_uploads = result.get("skipped", None)
        images_skipped = result.get("images_skipped", None)
        if skipped_uploads is not None or images_skipped is not None:
            set_stat("pending", (skipped_uploads or 0) + (images_skipped or 0))

        page.update()

    # --- Status Bar ---
    status_indicator = ft.Container(
        width=10,
        height=10,
        bgcolor=T.OK,
        border_radius=5,
    )

    status_text = ft.Text(
        tr("status.ready"),
        size=14,
        weight=ft.FontWeight.W_500,
        color=T.TEXT,
    )

    progress_ring = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)

    status_bar = ft.Container(
        content=ft.Row(
            [
                ft.Semantics(
                    label="tour:status",
                    container=True,
                    # Con el texto en su propio nodo, el ancla no es una hoja y Flutter
                    # la expone en aria-label (en una hoja la pone como texto).
                    content=ft.Row(
                        [status_indicator, ft.Semantics(container=True, content=status_text)],
                        spacing=8,
                    ),
                ),
                progress_ring,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.padding.Padding.symmetric(horizontal=24, vertical=12),
        bgcolor=T.BG_SECONDARY,
        border=T.BORDER_BOTTOM,
    )

    def set_status(text, color=T.OK, loading=False):
        status_indicator.bgcolor = color
        status_text.value = text
        progress_ring.visible = loading
        page.update()

    # --- Operation Cards ---
    def create_operation_card(icon, title, description, on_click, color, badge_text=None, tour_id=None):
        badge = None
        if badge_text:
            badge = ft.Container(
                content=ft.Text(badge_text, size=10, weight=ft.FontWeight.BOLD, color=T.ON_ACCENT),
                bgcolor=color,
                border_radius=T.RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=2),
            )

        body = ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(icon, color=color, size=22),
                                bgcolor=T.BG_PRIMARY,
                                border_radius=T.RADIUS,
                                padding=10,
                                width=44,
                                height=44,
                                alignment=ft.alignment.Alignment(0, 0),
                            ),
                            ft.Container(expand=True),
                            badge if badge else ft.Container(),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Text(
                        title,
                        size=15,
                        weight=ft.FontWeight.BOLD,
                        color=T.TEXT,
                    ),
                    ft.Text(
                        description,
                        size=13,
                        color=T.TEXT_2,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    T.primary_button(tr("common.run"), Icons.PLAY_ARROW_ROUNDED, on_click),
                ],
                spacing=10,
                alignment=ft.MainAxisAlignment.START,
            )
        col = {"xs": 12, "sm": 6, "md": 4, "lg": 4, "xl": 3}
        if not tour_id:
            return T.card(body, col=col)
        # Ancla DOM para el recorrido (driver.js, assets/tour/tour.js): envuelve la
        # tarjeta entera para que el resaltado cubra también su borde.
        return ft.Semantics(label=tour_id, container=True, content=T.card(body), col=col)

    # --- Logs Panel ---
    logs_list = ft.ListView(
        spacing=4,
        padding=10,
        auto_scroll=True,
        height=250,
    )

    def add_log(message, level="info", timestamp=None, remember=True):
        timestamp = timestamp or datetime.now().strftime("%H:%M:%S")
        if remember:
            # El registro sobrevive al cambio de idioma (cada línea queda en el
            # idioma en que se escribió).
            session["logs"].append((timestamp, message, level))
            del session["logs"][:-100]
        color = {
            "info": T.ACCENT_HOVER,
            "success": T.OK,
            "warning": T.WARN,
            "error": T.DANGER,
        }.get(level, T.TEXT_2)

        log_entry = ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        width=6,
                        height=6,
                        bgcolor=color,
                        border_radius=3,
                        margin=ft.margin.Margin.only(top=6),
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                f"{timestamp}",
                                size=11,
                                color=T.TEXT_3,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Text(
                                message,
                                size=13,
                                color=T.TEXT,
                                selectable=True,
                            ),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=8,
            border_radius=T.RADIUS,
            bgcolor=T.BG_INPUT,
        )

        logs_list.controls.append(log_entry)
        if len(logs_list.controls) > 100:
            logs_list.controls.pop(0)
        page.update()

    def clear_logs(e=None):
        logs_list.controls.clear()
        session["logs"].clear()
        page.update()

    # --- Confirmation Dialog ---
    confirm_dialog = ft.AlertDialog(
        modal=True,
        bgcolor=T.BG_SECONDARY,
        title=ft.Text(tr("confirm.title"), color=T.TEXT),
        content=ft.Text(tr("confirm.body"), color=T.TEXT_2),
        actions=[
            ft.TextButton(tr("common.cancel"), on_click=lambda e: page.pop_dialog()),
            ft.FilledButton(tr("common.confirm"), on_click=lambda e: None),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    pending_action = None

    progress_dialog = ft.AlertDialog(
        modal=True,
        bgcolor=T.BG_SECONDARY,
        title=ft.Text(tr("progress.title"), color=T.TEXT),
        content=ft.Column(
            [
                ft.ProgressRing(width=40, height=40),
                ft.Text(tr("progress.body"), color=T.TEXT_2),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=20,
        ),
        actions=[],
        actions_alignment=ft.MainAxisAlignment.CENTER,
    )
    def show_confirm(action, title, message):
        nonlocal pending_action
        pending_action = action
        confirm_dialog.title.value = title
        confirm_dialog.content.value = message

        def on_confirm_click(e):
            page.pop_dialog()
            action()

        confirm_dialog.actions[1].on_click = on_confirm_click
        page.show_dialog(confirm_dialog)

    # --- Workspace Explorer Dialog ---
    explorer_dialog = ft.AlertDialog(
        modal=True,
        bgcolor=T.BG_SECONDARY,
        title=ft.Text(tr("scan.title"), color=T.TEXT),
        content=ft.Container(width=500, height=400),
        actions=[
            ft.TextButton(tr("common.close"), on_click=lambda e: page.pop_dialog()),
        ],
    )
    def show_workspaces(result):
        if result.get("status") != "success":
            return
        explorer_dialog.title = ft.Text(tr("scan.title"), color=T.TEXT)

        workspaces = result.get("workspaces", {})
        if not workspaces:
            explorer_dialog.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(Icons.FOLDER_OFF_OUTLINED, size=48, color=T.BORDER_STRONG),
                        ft.Text(tr("scan.none"), color=T.TEXT_2),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                alignment=ft.alignment.Alignment(0, 0),
                width=400,
                height=300,
            )
        else:
            workspace_items = []
            for name, data in workspaces.items():
                files_chips = []
                for fname in data["files"][:5]:
                    files_chips.append(
                        ft.Chip(
                            label=ft.Text(fname, size=12, color=T.TEXT_2),
                            bgcolor=T.ACCENT_WASH,
                            border_side=ft.BorderSide(1, T.BORDER),
                        )
                    )
                if len(data["files"]) > 5:
                    files_chips.append(
                        ft.Text(tr("scan.more", count=len(data['files']) - 5), size=12, color=T.TEXT_2)
                    )

                workspace_items.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(Icons.FOLDER_OUTLINED, color=T.ACCENT_HOVER, size=20),
                                        ft.Text(name, size=14, weight=ft.FontWeight.BOLD, color=T.TEXT),
                                        ft.Container(expand=True),
                                        ft.Container(
                                            content=ft.Text(f"{data['file_count']}", size=11, weight=ft.FontWeight.BOLD, color=T.ON_ACCENT),
                                            bgcolor=T.ACCENT_HOVER,
                                            border_radius=12,
                                            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=2),
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(data["path"], size=11, color=T.TEXT_3),
                                ft.Row(
                                    files_chips,
                                    spacing=4,
                                    run_spacing=4,
                                    wrap=True,
                                ) if files_chips else ft.Text(tr("scan.noFiles"), size=12, color=T.TEXT_3, italic=True),
                            ],
                            spacing=6,
                        ),
                        padding=12,
                        border_radius=T.RADIUS,
                        bgcolor=T.BG_INPUT,
                        border=ft.border.Border.all(1, T.BORDER),
                        margin=ft.margin.Margin.only(bottom=8),
                    )
                )

            explorer_dialog.content = ft.Column(
                workspace_items,
                scroll=ft.ScrollMode.AUTO,
                spacing=0,
                height=400,
            )

        page.show_dialog(explorer_dialog)

    def show_simulation(result):
        """Qué haría la carga completa: huérfanos que se borrarían y archivos que se subirían."""
        if result.get("status") != "success":
            return
        titulo = tr("simulation.titleSync") if demo_state["demo"] else tr("simulation.titleClean")
        explorer_dialog.title = ft.Text(titulo, color=T.TEXT)

        def lista(titulo, nombres, color, limite):
            if not nombres:
                return ft.Text(tr("simulation.none", title=titulo), size=12, color=T.TEXT_3, italic=True)
            filas = [ft.Text(tr("simulation.count", title=titulo, count=len(nombres)), size=12, weight=ft.FontWeight.BOLD, color=color)]
            filas += [ft.Text(n, size=11, color=T.TEXT_2, selectable=True) for n in nombres[:limite]]
            if len(nombres) > limite:
                filas.append(ft.Text(tr("simulation.more", count=len(nombres) - limite), size=11, color=T.TEXT_3))
            return ft.Column(filas, spacing=2)

        items = [ft.Text(result.get("message", ""), size=13, color=T.TEXT)]
        for name, data in result.get("simulation", {}).items():
            encabezado = name + (tr("simulation.wouldCreate") if data.get("nuevo") else "")
            items.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [ft.Icon(Icons.FOLDER_OUTLINED, color=T.ACCENT_HOVER, size=20),
                                 ft.Text(encabezado, size=14, weight=ft.FontWeight.BOLD, color=T.TEXT)],
                                spacing=8,
                            ),
                            *(
                                [ft.Text(tr("simulation.blocked", reason=data['borrado_bloqueado']),
                                         size=13, color=T.DANGER)]
                                if data.get("borrado_bloqueado")
                                else []
                            ),
                            lista(tr("simulation.notDeleted") if data.get("borrado_bloqueado")
                                  else tr("simulation.wouldDelete"), data.get("huerfanos", []), T.WARN, 20),
                            lista(tr("simulation.wouldUpload"), data.get("a_subir", []), T.TEAL, 10),
                            *(
                                [lista(tr("simulation.noQuota"), data["sin_cupo"], T.DANGER, 10)]
                                if data.get("sin_cupo")
                                else []
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=12,
                    border_radius=T.RADIUS,
                    bgcolor=T.BG_INPUT,
                    border=ft.border.Border.all(1, T.BORDER),
                    margin=ft.margin.Margin.only(top=8),
                )
            )
        explorer_dialog.content = ft.Column(items, scroll=ft.ScrollMode.AUTO, spacing=0, height=400)
        page.show_dialog(explorer_dialog)

    # --- Config Editor Dialog ---
    config_fields = {}
    config_schema = ConfigManager.get_schema()

    def build_config_editor():
        fields = []
        config_fields.clear()

        for field in config_schema:
            key = field["key"]
            label = tr(f"config.field.{key}") if f"config.field.{key}" in i18n.ES else field["label"]
            current_val = config.get(key, "")

            if field["type"] == "bool":
                sw = ft.Switch(
                    value=bool(current_val),
                    active_color=T.ACCENT,
                    active_track_color=T.ACCENT,
                )
                config_fields[key] = sw
                row = ft.Row(
                    [
                        ft.Text(label, size=14, color=T.TEXT),
                        ft.Container(expand=True),
                        sw,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            elif field["type"] == "select":
                dd = T.dropdown(
                    value=str(current_val),
                    options=[ft.dropdown.Option(opt) for opt in field["options"]],
                    dense=True,
                    content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
                    text_size=13,
                    width=180,
                )
                config_fields[key] = dd
                row = ft.Row(
                    [
                        ft.Text(label, size=14, color=T.TEXT, expand=True),
                        dd,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            else:
                pw = field["type"] == "password"
                tf = T.textfield(
                    value=str(current_val) if current_val is not None else "",
                    password=pw,
                    can_reveal_password=pw,
                    dense=True,
                    content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
                    text_size=13,
                    width=280,
                )
                config_fields[key] = tf
                row = ft.Row(
                    [
                        ft.Text(label, size=14, color=T.TEXT, expand=True),
                        tf,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )

            fields.append(row)

        return ft.Column(fields, spacing=14, scroll=ft.ScrollMode.AUTO, height=450)

    config_editor_content = build_config_editor()

    config_dialog = ft.AlertDialog(
        modal=True,
        bgcolor=T.BG_SECONDARY,
        title=ft.Row(
            [
                ft.Icon(Icons.TUNE_OUTLINED, color=T.ACCENT_HOVER),
                ft.Text(tr("config.title"), size=18, weight=ft.FontWeight.BOLD, color=T.TEXT),
            ],
            spacing=8,
        ),
        content=ft.Container(
            content=config_editor_content,
            width=520,
        ),
        actions=[
            ft.TextButton(
                tr("common.cancel"),
                icon=Icons.CLOSE_OUTLINED,
                on_click=lambda e: page.pop_dialog(),
            ),
            ft.FilledButton(
                tr("common.save"),
                icon=Icons.SAVE_OUTLINED,
                on_click=lambda e: save_config(),
                style=ft.ButtonStyle(
                    bgcolor=T.ACCENT,
                    color=T.ON_ACCENT,
                    shape=T.SHAPE,
                ),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    def save_config():
        for field in config_schema:
            key = field["key"]
            ctrl = config_fields[key]
            if field["type"] == "bool":
                config.set(key, ctrl.value)
            elif field["type"] == "number":
                try:
                    config.set(key, int(ctrl.value))
                except (ValueError, TypeError):
                    config.set(key, DEFAULTS.get(key, 0))
            else:
                config.set(key, ctrl.value)

        if config.save():
            manager.api_key = os.getenv("ANYTHINGLLM_API_KEY") or config.get("anythingllm_api_key", "")
            manager.base_url = os.getenv("ANYTHINGLLM_BASE_URL") or config.get("anythingllm_base_url", "http://localhost:3000")
            manager.ollama_url = os.getenv("OLLAMA_BASE_URL") or config.get("ollama_base_url", "http://localhost:11434")
            manager.ollama_model = os.getenv("OLLAMA_MODEL") or config.get("ollama_model", "llava:latest")
            manager.image_description_active = config.get("image_description_active", True)
            manager.watched_root = os.getenv("WATCHED_FOLDERS_ROOT") or config.get("watched_folders_root", "")
            page.title = config.get("app_title", "InfoHub File Manager")
            page.update()

            page.pop_dialog()
            show_snackbar(tr("config.saved"), T.OK_DEEP)
            add_log(tr("config.savedLog"), "success")
        else:
            show_snackbar(tr("config.saveFailed"), T.DANGER_DEEP)

    def open_config_editor(e=None):
        for field in config_schema:
            key = field["key"]
            ctrl = config_fields[key]
            val = config.get(key, "")
            if field["type"] == "bool":
                ctrl.value = bool(val)
            else:
                ctrl.value = str(val) if val is not None else ""
        page.show_dialog(config_dialog)

    # ========== OPERATION HANDLERS ==========

    def log_operation(operation_name: str, result: dict, show_progress: bool = False):
        """Log operation result and update UI"""
        if show_progress:
            page.pop_dialog()  # ponytail: stack API keeps dialog state true even if a patch got lost

        level = result.get("status", "info")

        if level == "success":
            set_status(tr("status.done", name=operation_name), T.OK)
            add_log(f"{operation_name}: {result.get('message', 'OK')}", "success")
            show_snackbar(tr("ops.doneSnack", name=operation_name), T.OK_DEEP)
        elif level == "warning":
            set_status(tr("status.warning", name=operation_name), T.WARN)
            add_log(f"{operation_name}: {result.get('message', tr('ops.warning'))}", "warning")
            show_snackbar(result.get("message", tr("ops.warning")), T.WARN_DEEP)
        else:
            set_status(tr("status.failed", name=operation_name), T.DANGER)
            add_log(f"{operation_name}: {result.get('message', str(result))}", "error")
            show_snackbar(tr("ops.errorSnack", name=operation_name, message=result.get("message", "")), T.DANGER_DEEP)

        logger.info(f"{operation_name}: {result}")
        nonlocal is_processing
        is_processing = False
        session["busy"] = False
        progress_ring.visible = False
        page.update()

    # Las operaciones se identifican por clave (scan, simulate…); el nombre
    # visible sale del diccionario («ops.<clave>.title»).
    def wrap_operation(op, fn, confirm=False, show_progress=False):
        name = tr(f"ops.{op}.title")
        dialog_title = name
        dialog_msg = tr(f"ops.{op}.confirm") if confirm else ""

        def handler(e):
            nonlocal is_processing
            if is_processing:
                show_snackbar(tr("ops.busy"), T.WARN_DEEP)
                return

            def execute():
                nonlocal is_processing
                is_processing = True
                session["busy"] = True

                if show_progress:
                    progress_dialog.title.value = tr("ops.inProgress", name=name)
                    progress_dialog.content.value = ft.Column(
                        [
                            ft.ProgressRing(width=40, height=40),
                            ft.Text(tr("ops.processingFiles"), color=T.TEXT_2),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=20,
                    )
                    page.show_dialog(progress_dialog)
                page.update()

                set_status(tr("status.running", name=name), T.ACCENT_HOVER, loading=True)
                add_log(tr("ops.starting", name=name), "info")

                def run_in_thread():
                    try:
                        result = fn()
                        log_operation(name, result, show_progress)
                        if result.get("status") in ("success", "warning"):
                            update_stats(result)
                            if op == "scan":
                                show_workspaces(result)
                            elif op in ("simulate", "demoSimulate"):
                                show_simulation(result)
                            if op in DEMO_OPERATIONS:
                                refresh_demo()
                    except Exception as ex:
                        log_operation(name, {"status": "error", "message": str(ex)}, show_progress)

                threading.Thread(target=run_in_thread, daemon=True).start()

            if confirm:
                show_confirm(execute, dialog_title, dialog_msg)
            else:
                execute()

        return handler

    on_sort_files = wrap_operation("sort", manager.sort_files, confirm=True, show_progress=True)
    on_clean_folders = wrap_operation("clean", manager.clean_folders, confirm=True)
    on_scan_files = wrap_operation("scan", manager.scan_files)
    on_simulate_clean = wrap_operation("simulate", manager.simulate_clean)
    on_full_upload = wrap_operation("full", manager.full_upload_and_clean, confirm=True, show_progress=True)
    on_create_image_descriptions = wrap_operation(
        "images", manager.create_image_descriptions, confirm=True, show_progress=True
    )

    # ========== MODO DEMO ==========
    # Un prospecto de una demo de InfoHub (demo_mode.py): elige una carpeta,
    # el panel crea una subcarpeta por workspace y «Sincronizar» sube y quita.
    demo_state = {"demo": None, "sync": None}
    DEMO_OPERATIONS = ("demoSync", "demoSimulate")

    demo_title = ft.Text("", size=18, weight=ft.FontWeight.BOLD, color=T.TEXT)
    demo_quota = ft.Text("", size=13, color=T.TEXT_2)
    demo_folder = T.textfield(
        label=tr("demo.folder"),
        value=config.get("demo_folder", ""),
        dense=True,
        expand=True,
        text_size=13,
        hint_text=tr("demo.folderHint"),
        on_submit=lambda e: use_demo_folder(demo_folder.value),
    )
    demo_workspaces = ft.Column(spacing=6)

    def demo_folder_path() -> str:
        return (demo_folder.value or "").strip()

    def render_demo(demo: dict):
        demo_state["demo"] = demo
        days = demo_mode.days_left(demo.get("expiresAt"))
        session["demo"] = demo
        demo_title.value = tr("demo.title", company=demo.get("company", ""))
        remaining = (tr("demo.expiresToday") if days == 0 else tr("demo.oneDayLeft") if days == 1
                     else tr("demo.daysLeft", days=days))
        demo_quota.value = tr(
            "demo.quota", days=remaining, used=demo["usedDocs"], max=demo["maxDocs"],
            usedSpace=tr.size(demo["usedBytes"]), maxSpace=tr.size(demo["maxBytes"]),
        )
        set_stat("workspaces", len(demo.get("workspaces", [])))
        demo_workspaces.controls = [
            ft.Row(
                [
                    ft.Icon(Icons.FOLDER_OUTLINED, color=T.ACCENT_HOVER, size=18),
                    ft.Text(w["name"], size=14, weight=ft.FontWeight.W_500, color=T.TEXT, expand=True),
                    ft.Text(
                        tr.plural("demo.docsInInfohub", len(w["documents"])),
                        size=12,
                        color=T.TEXT_2,
                    ),
                ],
                spacing=8,
            )
            for w in demo.get("workspaces", [])
        ]

    def refresh_demo():
        """Corre en un hilo: vuelve a leer la demo (cuota y documentos)."""
        sync = demo_state["sync"]
        demo = sync.fetch() if sync else None
        if demo:
            render_demo(demo)
            page.update()

    def use_demo_folder(path: str):
        path = (path or "").strip()
        demo = demo_state["demo"]
        if not path or not demo:
            return
        try:
            folders = demo_state["sync"].ensure_folders(path, demo)
        except Exception as ex:
            show_snackbar(tr("demo.folderFailed", error=ex), T.DANGER_DEEP)
            return
        demo_folder.value = path
        config.set("demo_folder", path)
        config.save()
        render_demo(demo)
        add_log(tr("demo.folderLog", path=path, folders=", ".join(f.name for f in folders)), "success")
        show_snackbar(tr("demo.folderReady"), T.OK_DEEP)
        page.update()

    def choose_demo_folder(e=None):
        def _pick():
            path = demo_mode.choose_folder(demo_folder_path(), tr("demo.chooseFolderTitle"))
            if path:
                use_demo_folder(path)
            elif path is None:  # sin selector; "" es que se canceló
                show_snackbar(tr("demo.noPicker"), T.WARN_DEEP)

        threading.Thread(target=_pick, daemon=True).start()

    on_demo_sync = wrap_operation(
        "demoSync",
        lambda: demo_state["sync"].sync(demo_folder_path()),
        confirm=True,
        show_progress=True,
    )
    on_demo_simulate = wrap_operation(
        "demoSimulate",
        lambda: demo_state["sync"].simulate(demo_folder_path()),
    )

    demo_section = ft.Container(
        content=T.card(
            ft.Column(
                [
                    demo_title,
                    demo_quota,
                    ft.Text(
                        tr("demo.steps"),
                        size=13,
                        color=T.TEXT_2,
                    ),
                    ft.Row(
                        [
                            demo_folder,
                            ft.OutlinedButton(tr("demo.chooseFolder"), icon=Icons.FOLDER_OPEN_OUTLINED, on_click=choose_demo_folder),
                        ],
                        spacing=8,
                    ),
                    demo_workspaces,
                    ft.Row(
                        [
                            T.primary_button(tr("demo.sync"), Icons.CLOUD_SYNC_OUTLINED, on_demo_sync),
                            ft.OutlinedButton(tr("demo.simulate"), icon=Icons.FIND_IN_PAGE_OUTLINED, on_click=on_demo_simulate),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=12,
            )
        ),
        padding=ft.padding.Padding.only(bottom=16),
        visible=False,
    )

    def enter_demo_mode(demo: dict, quiet: bool = False):
        """Muestra el panel de la demo en lugar de las operaciones de administración."""
        demo_state["sync"] = DemoSync(manager.base_url, manager.session_token, manager, tr)
        manager.image_description_active = False
        render_demo(demo)
        demo_section.visible = True
        operations_section.visible = False
        # Sin configuración ni recorrido: no aplican a la demo, y el recorrido
        # espera el botón de configuración para empezar, así que no se abre solo.
        config_button.visible = False
        help_button.visible = False
        if not quiet:
            add_log(tr("demo.modeLog", count=len(demo.get("workspaces", [])), company=demo.get("company", "")), "info")
        if demo_folder_path():
            use_demo_folder(demo_folder_path())
        page.update()

    # ========== BUILD UI ==========

    config_button = ft.Semantics(
        label="tour:config",
        container=True,
        content=ft.IconButton(
            icon=Icons.SETTINGS_OUTLINED,
            icon_color=T.TEXT,
            tooltip=tr("bar.settings"),
            on_click=open_config_editor,
        ),
    )
    # Sin acción en Python: assets/tour/tour.js abre el recorrido con el clic.
    help_button = ft.Semantics(
        label="tour:help",
        container=True,
        content=ft.IconButton(
            icon=Icons.HELP_OUTLINE,
            icon_color=T.TEXT,
            tooltip=tr("bar.tour"),
        ),
    )

    # AppBar
    app_bar = ft.AppBar(
        title=T.brand("File Manager"),
        center_title=False,
        bgcolor=T.BG_PRIMARY,
        elevation=0,
        actions=[
            *(
                [
                    ft.Semantics(
                        label="tour:home",
                        container=True,
                        content=ft.IconButton(
                            icon=Icons.HOME_OUTLINED,
                            icon_color=T.TEXT,
                            tooltip=tr("bar.home"),
                            on_click=lambda e: go_to_portal(),
                        ),
                    )
                ]
                if PORTAL_URL
                else []
            ),
            ft.IconButton(
                icon=Icons.REFRESH_OUTLINED,
                icon_color=T.TEXT,
                tooltip=tr("bar.refresh"),
                on_click=lambda e: (
                    set_status(tr("status.ready"), T.OK),
                    show_snackbar(tr("status.refreshed"), T.OK_DEEP),
                ),
            ),
            ft.Container(content=language_dropdown(), padding=ft.padding.Padding.symmetric(horizontal=4)),
            config_button,
            help_button,
        ],
    )

    # Operations Grid
    operations_grid = ft.ResponsiveRow(
        [
            create_operation_card(
                Icons.CLOUD_SYNC_OUTLINED,
                tr("ops.full.title"),
                tr("ops.full.description"),
                on_full_upload,
                T.TEAL,
                tour_id="tour:op-full",
            ),
            create_operation_card(
                Icons.FIND_IN_PAGE_OUTLINED,
                tr("ops.simulate.title"),
                tr("ops.simulate.description"),
                on_simulate_clean,
                T.ACCENT_HOVER,
                tour_id="tour:op-simulate",
            ),
            create_operation_card(
                Icons.SYNC_OUTLINED,
                tr("ops.sort.title"),
                tr("ops.sort.description"),
                on_sort_files,
                T.ACCENT_HOVER,
            ),
            create_operation_card(
                Icons.CLEANING_SERVICES_OUTLINED,
                tr("ops.clean.title"),
                tr("ops.clean.description"),
                on_clean_folders,
                T.WARN,
            ),
            create_operation_card(
                Icons.SEARCH_OUTLINED,
                tr("ops.scan.title"),
                tr("ops.scan.description"),
                on_scan_files,
                T.TEAL,
                tour_id="tour:op-scan",
            ),
            create_operation_card(
                Icons.IMAGE_OUTLINED,
                tr("ops.images.title"),
                tr("ops.images.description"),
                on_create_image_descriptions,
                T.WARN,
                tour_id="tour:op-images",
            ),
        ],
        spacing=16,
        run_spacing=16,
    )

    # Logs Panel
    logs_panel = T.card(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(Icons.TERMINAL_OUTLINED, color=T.TEXT_2, size=18),
                                    ft.Text(tr("logs.title"), size=14, weight=ft.FontWeight.BOLD, color=T.TEXT),
                                ],
                                spacing=8,
                            ),
                            ft.Container(expand=True),
                            ft.TextButton(
                                tr("logs.clear"),
                                icon=Icons.CLEAR_ALL_OUTLINED,
                                on_click=clear_logs,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=logs_list,
                        border=ft.border.Border.all(1, T.BORDER),
                        border_radius=T.RADIUS,
                        bgcolor=T.BG_INPUT,
                    ),
                ],
                spacing=10,
            ),
            padding=16,
    )

    # Main Layout
    main_content = ft.Container(
        content=ft.Column(
            [
                # Stats Row
                ft.Container(
                    content=ft.Semantics(
                        label="tour:stats",
                        container=True,
                        content=ft.ResponsiveRow(
                            [
                                workspaces_stat,
                                files_stat,
                                uploaded_stat,
                                pending_stat,
                            ],
                            spacing=16,
                            run_spacing=16,
                        ),
                    ),
                    padding=ft.padding.Padding.only(bottom=16),
                ),
                # Demo (modo demo, oculta para el resto)
                demo_section,
                # Operations Section
                operations_section := ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(tr("ops.title"), size=18, weight=ft.FontWeight.BOLD, color=T.TEXT),
                                    ft.Container(expand=True),
                                    ft.Text(
                                        f"v1.0 | {datetime.now().strftime('%Y-%m-%d')}",
                                        size=12,
                                        color=T.TEXT_3,
                                    ),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            operations_grid,
                        ],
                        spacing=16,
                    ),
                    padding=ft.padding.Padding.only(bottom=16),
                ),
                # Logs Panel Row
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            content=ft.Semantics(label="tour:logs", container=True, content=logs_panel),
                            col={"xs": 12, "sm": 12, "md": 8, "lg": 8, "xl": 8},
                        ),
                    ],
                    spacing=16,
                    run_spacing=16,
                ),
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
        ),
        padding=ft.padding.Padding.symmetric(horizontal=24, vertical=20),
        expand=True,
    )

    page.appbar = app_bar
    page.add(
        ft.Column(
            [
                status_bar,
                main_content,
            ],
            spacing=0,
            expand=True,
        )
    )

    # Funciones opcionales que activa la licencia de InfoHub (features.py). Sin
    # API key (p. ej. un prospecto de una demo) no hay a quién preguntar.
    if not first_build:
        # Cambio de idioma: se repone lo que había (registro, modo demo).
        for timestamp, message, level in list(session["logs"]):
            add_log(message, level, timestamp=timestamp, remember=False)
        if signed_in and session["demo"]:
            enter_demo_mode(session["demo"], quiet=True)
        page.update()
        return

    current_features = (
        features.fetch_features(manager.base_url, manager.api_key, timeout=5) if manager.api_key else []
    )

    # Initial log
    add_log(tr("logs.started"), "success")
    add_log(
        tr("logs.connected", url=manager.base_url,
           features=", ".join(current_features) or tr("logs.noFeatures")),
        "info",
    )

    # Idioma de la instancia: llega en segundo plano para no demorar el arranque.
    threading.Thread(
        target=lambda: apply_instance_language(i18n.fetch_instance_language(manager.base_url)),
        daemon=True,
    ).start()

    if sso_ticket:
        _handle_ticket_login(sso_ticket)


if __name__ == "__main__":
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        port=int(os.getenv("APP_PORT", 8500)),
        assets_dir=str(Path(BASE_DIR) / "assets"),
    )
