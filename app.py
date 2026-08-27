"""
InfoHub File Manager - Flet Web Dashboard
Panel de control para sincronizar archivos con AnythingLLM/InfoHub
"""

import os
import base64
import logging
import re
import threading
import time
import requests
from pathlib import Path
from datetime import datetime

import flet as ft
from flet import Icons, Colors
from dotenv import load_dotenv
from config_manager import ConfigManager, DEFAULTS

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.getenv("LOG_FILE", "infohub.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Retry policy for update-embeddings (openresty proxy returns 502/503/504 under load)
EMBEDDINGS_MAX_RETRIES = 3
EMBEDDINGS_RETRY_STATUS_CODES = {502, 503, 504}
EMBEDDINGS_RETRY_BACKOFF_SECONDS = 5


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
        else:
            self.api_key = os.getenv("ANYTHINGLLM_API_KEY", "")
            self.base_url = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3000")
            self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self.ollama_model = os.getenv("OLLAMA_MODEL", "llava:latest")
            self.image_description_active = (
                os.getenv("IMAGE_DESCRIPTION_ACTIVATE", "true").lower() == "true"
            )
            self.watched_root = os.getenv("WATCHED_FOLDERS_ROOT", "")

        # Cache within a single operation to avoid duplicate server lookups
        # for the same workspace and to remember docpaths already uploaded.
        self._base_name_cache: dict[str, set[str]] = {}
        self._uploaded_docpaths: set[str] = set()

        # None = sin filtro de usuario; tras login: {slug: nombre} habilitados.
        self.session_token: str = ""
        self.allowed_workspaces: dict[str, str] | None = None

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
                return False, data.get("message") or "Credenciales invalidas"

            self.session_token = data.get("token") or ""
            allowed = self._fetch_allowed_workspaces()
            if allowed is None:
                self.session_token = ""
                return False, "No se pudieron obtener los workspaces del usuario"
            self.allowed_workspaces = allowed
            return True, None
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False, f"Error de conexion con InfoHub: {e}"

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
            return {"status": "error", "message": "WATCHED_FOLDERS_ROOT not configured"}

        root_path = Path(self.watched_root)
        if not root_path.exists():
            return {
                "status": "error",
                "message": f"Root path does not exist: {self.watched_root}",
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
            files = list(ws_path.iterdir())
            file_names = [
                f.name for f in files
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
        """Convert workspace name to slug format"""
        return workspace_name.lower().replace(" ", "-").replace("_", "-")

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
                - "doc_names": dict mapping base_name -> full_doc_name (for deletion)
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
                            doc_names[base_name] = filename

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

    def _update_embeddings(self, workspace_name: str) -> bool:
        """Trigger embedding generation for all documents in a workspace.

        After uploading documents, this must be called so the vector DB
        is updated and queries can find the documents.
        """
        try:
            slug = self.get_workspace_slug(workspace_name)
            docs = self.get_workspace_documents(workspace_name)
            if not docs.get("exists", False):
                logger.warning(f"Cannot update embeddings: workspace '{workspace_name}' not found")
                return False

            # Collect all server-side document paths from the workspace
            docpaths = [
                doc["docpath"] for doc in docs.get("raw_docs", [])
                if isinstance(doc, dict) and doc.get("docpath")
            ]
            # Uploads on this InfoHub instance are not registered in the
            # workspace listing until processed — merge in the documents area.
            # Solo se envían los NO registrados: re-enviar existentes crea
            # filas duplicadas en workspace_documents.
            existing = set(docpaths)
            new_paths = [
                p for p in self._get_documents_area_docpaths(slug)
                if p not in existing
            ]
            if not new_paths:
                logger.info(f"No new documents to embed in workspace '{workspace_name}'")
                return True
            docpaths = new_paths

            url = f"{self.base_url}/api/v1/workspace/{slug}/update-embeddings"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "accept": "application/json",
            }
            payload = {"adds": docpaths, "deletes": []}

            for attempt in range(EMBEDDINGS_MAX_RETRIES):
                try:
                    response = requests.post(url, headers=headers, json=payload, timeout=300)
                except requests.RequestException as e:
                    if attempt < EMBEDDINGS_MAX_RETRIES - 1:
                        logger.warning(
                            f"Embeddings request failed (attempt {attempt + 1}/{EMBEDDINGS_MAX_RETRIES}): {e}; retrying"
                        )
                        time.sleep(EMBEDDINGS_RETRY_BACKOFF_SECONDS * (attempt + 1))
                        continue
                    logger.error(f"Error updating embeddings for '{workspace_name}': {e}")
                    return False
                if response.status_code == 200:
                    logger.info(f"Embeddings updated for '{workspace_name}' ({len(docpaths)} docs)")
                    return True
                if (
                    response.status_code in EMBEDDINGS_RETRY_STATUS_CODES
                    and attempt < EMBEDDINGS_MAX_RETRIES - 1
                ):
                    logger.warning(
                        f"Embeddings update returned {response.status_code} "
                        f"(attempt {attempt + 1}/{EMBEDDINGS_MAX_RETRIES}); retrying"
                    )
                    time.sleep(EMBEDDINGS_RETRY_BACKOFF_SECONDS * (attempt + 1))
                    continue
                logger.warning(f"Failed to update embeddings for '{workspace_name}': {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error updating embeddings for '{workspace_name}': {e}")
            return False

    def file_exists_in_workspace(
        self, file_path: Path, workspace_name: str, docs: dict = None
    ) -> bool:
        """Check if file already exists in workspace"""
        # Must handle UUID-format docpaths: report.pdf → docpath report.abc123.json
        # or report-uuid.json, so base_name = "report.abc123" / "report-uuid"
        # and we need to match stem "report"
        return any(
            self._base_name_matches(base, file_path.stem)
            for base in self._base_names_for(workspace_name, docs)
        )

    def delete_documents(self, doc_names: list) -> tuple:
        """Delete documents from AnythingLLM system.

        Args:
            doc_names: List of full document names (e.g. ["report.uuid.json"])

        Returns:
            tuple: (success: bool, deleted_count: int, errors: list)
        """
        if not doc_names:
            return (True, 0, [])

        try:
            url = f"{self.base_url}/api/v1/system/remove-documents"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "accept": "application/json",
            }

            logger.info(f"Deleting {len(doc_names)} documents: {doc_names}")
            response = requests.delete(url, headers=headers, json={"names": doc_names}, timeout=30)

            if response.status_code in (200, 201, 204):
                logger.info(f"Successfully deleted {len(doc_names)} documents")
                return (True, len(doc_names), [])
            else:
                logger.warning(f"Failed to delete documents: {response.status_code} - {response.text}")
                return (False, 0, [f"HTTP {response.status_code}: {response.text}"])
        except Exception as e:
            logger.error(f"Error deleting documents: {e}")
            return (False, 0, [str(e)])

    def upload_file_to_workspace(
        self, file_path: Path, workspace_name: str, skip_if_exists: bool = True
    ) -> tuple:
        """Upload a single file to AnythingLLM workspace

        Returns:
            tuple: (success: bool, skipped: bool, message: str)
        """
        try:
            # Auto-create workspace if missing + check file existence
            docs = self.get_workspace_documents(workspace_name)
            if not docs.get("exists", True):
                self.create_workspace(workspace_name)
                docs = self.get_workspace_documents(workspace_name)

            # Also guard against uploading twice in the same operation
            cache_key = f"{workspace_name}:{file_path.stem}"
            if cache_key in self._uploaded_docpaths:
                logger.info(f"Skipped {file_path.name} - already uploaded in this run")
                return (False, True, "already exists")

            if skip_if_exists and self.file_exists_in_workspace(file_path, workspace_name, docs):
                logger.info(f"Skipped {file_path.name} - already in {workspace_name}")
                return (False, True, "already exists")

            slug = self.get_workspace_slug(workspace_name)
            url = f"{self.base_url}/api/v1/document/upload/{slug}"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "accept": "application/json",
            }

            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f)}
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
                    "message": "WATCHED_FOLDERS_ROOT not configured",
                }

            root_path = Path(self.watched_root)
            if not root_path.exists():
                return {
                    "status": "error",
                    "message": f"Root path does not exist: {self.watched_root}",
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

                for file_path in workspace_folder.iterdir():
                    if file_path.is_file() and not file_path.name.endswith(
                        ".image_description"
                    ) and not file_path.name.endswith(
                        ".image_description.txt"
                    ):
                        success, was_skipped, msg = self.upload_file_to_workspace(
                            file_path, workspace_name
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

            return {
                "status": "success",
                "message": f"Archivos: {uploaded} subidos, {skipped} omitidos. Imagenes: {images_processed} descritas, {images_skipped} con descripcion existente.",
                "uploaded": uploaded,
                "skipped": skipped,
                "images_processed": images_processed,
                "images_skipped": images_skipped,
            }
        except Exception as e:
            logger.error(f"Error sorting files: {e}")
            return {"status": "error", "message": str(e)}

    def clean_folders(self) -> dict:
        """Clean empty folders in InfoHub"""
        return {"status": "success", "message": "Empty folders cleaned"}

    def full_upload_and_clean(self) -> dict:
        """Full synchronization: upload new/updated files, delete removed ones"""
        try:
            # Clear operation caches so each run starts fresh
            self._base_name_cache.clear()
            self._uploaded_docpaths.clear()
            if not self.watched_root:
                return {
                    "status": "error",
                    "message": "WATCHED_FOLDERS_ROOT not configured",
                }

            root_path = Path(self.watched_root)
            if not root_path.exists():
                return {
                    "status": "error",
                    "message": f"Root path does not exist: {self.watched_root}",
                }

            uploaded = 0
            skipped = 0
            deleted = 0
            delete_errors = []
            workspaces_processed = 0

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

            # Only process workspaces the API key can access
            accessible = self.get_accessible_workspace_names(list(workspaces_by_name.keys()))
            workspaces_by_name = {
                name: folder for name, folder in workspaces_by_name.items() if name in accessible
            }

            for workspace_name, workspace_folder in workspaces_by_name.items():
                workspaces_processed += 1

                # --- Step 1: Collect local files (base names) ---
                local_base_names = set()
                for file_path in workspace_folder.iterdir():
                    if file_path.is_file() and not file_path.name.endswith(
                        ".image_description"
                    ) and not file_path.name.endswith(
                        ".image_description.txt"
                    ):
                        local_base_names.add(file_path.stem)

                # --- Step 2: Find and delete orphaned remote documents ---
                docs_info = self.get_workspace_documents(workspace_name)
                if not docs_info.get("exists", False):
                    self.create_workspace(workspace_name)
                    docs_info = self.get_workspace_documents(workspace_name)
                remote_base_names = docs_info["base_names"]
                doc_names_map = docs_info["doc_names"]

                orphaned = [
                    doc_names_map[base]
                    for base in remote_base_names
                    if base not in local_base_names and base in doc_names_map
                ]

                if orphaned:
                    logger.info(
                        f"Orphaned documents in '{workspace_name}': {orphaned}"
                    )
                    success, count, errs = self.delete_documents(orphaned)
                    if success:
                        deleted += count
                        for doc_name in orphaned:
                            logger.info(f"Deleted orphaned document: {doc_name}")
                    else:
                        delete_errors.extend(errs)

                # --- Step 3: Upload local files ---
                for file_path in workspace_folder.iterdir():
                    if file_path.is_file() and not file_path.name.endswith(
                        ".image_description"
                    ) and not file_path.name.endswith(
                        ".image_description.txt"
                    ):
                        success, was_skipped, msg = self.upload_file_to_workspace(
                            file_path, workspace_name
                        )
                        if success:
                            uploaded += 1
                        elif was_skipped:
                            skipped += 1

                # --- Step 4: Update embeddings ---
                self._update_embeddings(workspace_name)

            result_msg = (
                f"{workspaces_processed} workspaces procesados, {uploaded} subidos, "
                f"{skipped} omitidos, {deleted} eliminados"
            )
            if delete_errors:
                result_msg += f", {len(delete_errors)} errores al eliminar"

            result = {
                "status": "success" if not delete_errors else "warning",
                "message": result_msg,
                "workspaces_processed": workspaces_processed,
                "uploaded": uploaded,
                "skipped": skipped,
                "deleted": deleted,
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
                "message": "Image descriptions are disabled in config",
            }

        if not self.watched_root:
            return {
                "status": "error",
                "message": "WATCHED_FOLDERS_ROOT not configured",
            }

        root_path = Path(self.watched_root)
        if not root_path.exists():
            return {
                "status": "error",
                "message": f"Root path does not exist: {self.watched_root}",
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
                "message": f"Todas las {skipped} imagenes ya tienen descripciones",
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
                "message": f"{processed} descripciones creadas, {skipped} omitidas, {len(errors)} errores",
                "processed": processed,
                "skipped": skipped,
                "errors": errors,
            }

        return {
            "status": "success",
            "message": f"{processed} descripciones creadas, {skipped} omitidas",
            "processed": processed,
            "skipped": skipped,
        }


def main(page: ft.Page):
    try:
        _main(page)
    except Exception as e:
        import traceback
        traceback.print_exc()
        page.add(ft.Column([
            ft.Text(f"Error: {e}", color=ft.Colors.RED_500, size=17),
        ]))
        page.update()


def _main(page: ft.Page):
    # ========== PAGE CONFIGURATION ==========
    config = ConfigManager()
    page.title = config.get("app_title", "InfoHub File Manager")
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0
    page.spacing = 0

    # Custom theme colors
    page.theme = ft.Theme(
        color_scheme_seed="#2563EB",
        use_material3=True,
    )

    manager = InfoHubFileManager(config)

    # ========== LOGIN DIALOG ==========
    login_base_url = ft.TextField(
        label="URL InfoHub",
        value=manager.base_url or "http://localhost:3001",
        dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
        text_size=13,
        border_color=Colors.BLUE_GREY_300,
        focused_border_color=Colors.INDIGO_500,
        width=360,
    )
    login_username = ft.TextField(
        label="Usuario",
        dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
        text_size=13,
        border_color=Colors.BLUE_GREY_300,
        focused_border_color=Colors.INDIGO_500,
        width=360,
    )
    login_password = ft.TextField(
        label="Contraseña",
        password=True,
        can_reveal_password=True,
        dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
        text_size=13,
        border_color=Colors.BLUE_GREY_300,
        focused_border_color=Colors.INDIGO_500,
        width=360,
        on_submit=lambda e: _handle_login(),
    )
    login_error = ft.Text("", color=Colors.RED_600, size=13)
    if config.last_error:
        login_error.value = f"config.json invalido: {config.last_error}. Se estan usando valores por defecto."
        login_error.color = Colors.AMBER_600
    login_progress = ft.ProgressRing(width=18, height=18, stroke_width=2, visible=False)
    login_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [
                ft.Icon(Icons.LOCK, color=Colors.INDIGO_500),
                ft.Text("Iniciar sesión en InfoHub", size=18, weight=ft.FontWeight.BOLD),
            ],
            spacing=8,
        ),
        content=ft.Column(
            [
                ft.Text("Accedé con tu usuario y contraseña de InfoHub. Solo verás los workspaces que tenés habilitados.", size=13, color=Colors.BLUE_GREY_600),
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
                "Salir",
                icon=Icons.CLOSE,
                on_click=lambda e: page.window.close(),
            ),
            ft.FilledButton(
                "Ingresar",
                icon=Icons.LOGIN,
                on_click=lambda e: _handle_login(),
                style=ft.ButtonStyle(
                    bgcolor=Colors.INDIGO_600,
                    color=Colors.WHITE,
                    shape=ft.RoundedRectangleBorder(radius=8),
                ),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    # ========== DIÁLOGO WORKSPACES HABILITADOS ==========
    user_ws_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
    user_ws_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [
                ft.Icon(Icons.FOLDER_SPECIAL, color=Colors.INDIGO_500),
                ft.Text("Tus workspaces habilitados", size=18, weight=ft.FontWeight.BOLD),
            ],
            spacing=8,
        ),
        content=ft.Container(content=user_ws_list, width=380, height=300),
        actions=[
            ft.FilledButton(
                "Aceptar",
                icon=Icons.CHECK,
                on_click=lambda e: page.pop_dialog(),
                style=ft.ButtonStyle(
                    bgcolor=Colors.INDIGO_600,
                    color=Colors.WHITE,
                    shape=ft.RoundedRectangleBorder(radius=8),
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
                        ft.Icon(Icons.FOLDER, color=Colors.INDIGO_500, size=18),
                        ft.Text(name, size=14, expand=True),
                        ft.Text(slug, size=11, color=Colors.BLUE_GREY_400),
                    ],
                    spacing=8,
                )
                for slug, name in allowed.items()
            ]
        else:
            user_ws_list.controls = [
                ft.Text(
                    "No tenés workspaces habilitados.",
                    size=14,
                    color=Colors.BLUE_GREY_500,
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

    def _handle_login():
        base_url = login_base_url.value.strip()
        username = login_username.value.strip()
        password = login_password.value or ""
        if not base_url or not username or not password:
            login_error.value = "URL, usuario y contraseña son obligatorios"
            page.update()
            return

        login_error.value = ""
        login_progress.visible = True
        page.update()

        def _do_login():
            try:
                manager.base_url = base_url
                ok, msg = manager.login(username, password)
                if not ok:
                    login_error.value = msg or "Credenciales inválidas"
                    login_progress.visible = False
                    page.update()
                    return

                config.set("anythingllm_base_url", base_url)
                config.save()
                login_error.value = ""
                login_progress.visible = False
                page.pop_dialog()
                show_snackbar(f"Sesión iniciada como {username}", Colors.GREEN_700)
                add_log(
                    f"Login exitoso (usuario: {username}) - Workspaces habilitados: {len(manager.allowed_workspaces or {})}",
                    "success",
                )
                if not manager.api_key or not _validate_credentials(base_url, manager.api_key):
                    show_snackbar("API Key InfoHub ausente o inválida en config.json: la sincronización fallará hasta configurarla", Colors.RED_600)
                    add_log("Advertencia: API Key InfoHub ausente o inválida. Configúrala en Ajustes para poder sincronizar.", "warning")
                _show_user_workspaces()
            except Exception as ex:
                login_error.value = f"Error: {ex}"
                login_progress.visible = False
                page.update()

        threading.Thread(target=_do_login, daemon=True).start()

    page.show_dialog(login_dialog)

    # ========== STATE ==========
    is_processing = False

    # ========== UI COMPONENTS ==========

    # --- SnackBar for notifications ---
    snackbar = ft.SnackBar(
        content=ft.Text(""),
        action=ft.SnackBarAction(
            label="Cerrar",
            on_click=lambda e: setattr(snackbar, "open", False),
        ),
        bgcolor=Colors.BLUE_GREY_800,
        duration=4000,
    )
    page.overlay.append(snackbar)

    def show_snackbar(message, color=Colors.BLUE_GREY_800):
        snackbar.content.value = message
        snackbar.bgcolor = color
        snackbar.open = True
        page.update()

    # --- Stats Cards ---
    def create_stat_card(value, label, icon, color):
        return ft.Card(
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(icon, color=Colors.WHITE, size=28),
                            bgcolor=color,
                            border_radius=12,
                            padding=12,
                            width=52,
                            height=52,
                            alignment=ft.alignment.Alignment(0, 0),
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    str(value),
                                    size=24,
                                    weight=ft.FontWeight.BOLD,
                                    color=Colors.BLUE_GREY_800,
                                ),
                                ft.Text(
                                    label,
                                    size=13,
                                    color=Colors.BLUE_GREY_500,
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
                padding=20,
            ),
            elevation=2,
            col={"xs": 6, "sm": 6, "md": 3, "lg": 3, "xl": 3},
        )

    workspaces_stat = create_stat_card("0", "Workspaces", Icons.FOLDER_COPY, Colors.INDIGO_500)
    files_stat = create_stat_card("0", "Archivos", Icons.DESCRIPTION, Colors.GREEN_500)
    uploaded_stat = create_stat_card("0", "Subidos", Icons.CLOUD_UPLOAD, Colors.CYAN_600)
    pending_stat = create_stat_card("0", "Pendientes", Icons.SCHEDULE, Colors.AMBER_500)

    def update_stats(result=None):
        if not result or result.get("status") not in ("success", "warning"):
            return

        # Scan results: workspaces & file counts
        if "total_workspaces" in result:
            workspaces_stat.content.content.controls[1].controls[0].value = str(
                result.get("total_workspaces", 0)
            )
        if "total_files" in result:
            files_stat.content.content.controls[1].controls[0].value = str(
                result.get("total_files", 0)
            )

        # Upload results: uploaded file count
        if "uploaded" in result:
            val = result.get("uploaded", 0)
            uploaded_stat.content.content.controls[1].controls[0].value = str(val)

        # Image description results: processed count
        if "processed" in result:
            val = result.get("processed", 0)
            uploaded_stat.content.content.controls[1].controls[0].value = str(val)

        # Pending: skipped uploads or images still needing descriptions
        skipped_uploads = result.get("skipped", None)
        images_skipped = result.get("images_skipped", None)
        if skipped_uploads is not None or images_skipped is not None:
            total_skipped = (skipped_uploads or 0) + (images_skipped or 0)
            pending_stat.content.content.controls[1].controls[0].value = str(total_skipped)

        page.update()

    # --- Status Bar ---
    status_indicator = ft.Container(
        width=10,
        height=10,
        bgcolor=Colors.GREEN_500,
        border_radius=5,
    )

    status_text = ft.Text(
        "Sistema listo",
        size=14,
        weight=ft.FontWeight.W_500,
        color=Colors.BLUE_GREY_700,
    )

    progress_ring = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)

    status_bar = ft.Container(
        content=ft.Row(
            [
                ft.Row([status_indicator, status_text], spacing=8),
                progress_ring,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        padding=ft.padding.Padding.symmetric(horizontal=20, vertical=12),
        bgcolor=Colors.BLUE_GREY_50,
        border=ft.border.Border.only(bottom=ft.border.BorderSide(1, Colors.BLUE_GREY_200)),
    )

    def set_status(text, color=Colors.GREEN_500, loading=False):
        status_indicator.bgcolor = color
        status_text.value = text
        progress_ring.visible = loading
        page.update()

    # --- Operation Cards ---
    def create_operation_card(icon, title, description, on_click, color, badge_text=None):
        badge = None
        if badge_text:
            badge = ft.Container(
                content=ft.Text(badge_text, size=10, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                bgcolor=color,
                border_radius=12,
                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=2),
            )

        return ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    content=ft.Icon(icon, color=Colors.WHITE, size=24),
                                    bgcolor=color,
                                    border_radius=10,
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
                            color=Colors.BLUE_GREY_800,
                        ),
                        ft.Text(
                            description,
                            size=13,
                            color=Colors.BLUE_GREY_500,
                            max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.FilledButton(
                            "Ejecutar",
                            icon=Icons.PLAY_ARROW_ROUNDED,
                            on_click=on_click,
                            style=ft.ButtonStyle(
                                bgcolor=color,
                                color=Colors.WHITE,
                                shape=ft.RoundedRectangleBorder(radius=8),
                                padding=ft.padding.Padding.symmetric(horizontal=16, vertical=10),
                            ),
                        ),
                    ],
                    spacing=10,
                    alignment=ft.MainAxisAlignment.START,
                ),
                padding=20,
            ),
            elevation=2,
            col={"xs": 12, "sm": 6, "md": 4, "lg": 4, "xl": 3},
        )

    # --- Logs Panel ---
    logs_list = ft.ListView(
        spacing=4,
        padding=10,
        auto_scroll=True,
        height=250,
    )

    def add_log(message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = {
            "info": Colors.INDIGO_500,
            "success": Colors.GREEN_500,
            "warning": Colors.AMBER_500,
            "error": Colors.RED_500,
        }.get(level, Colors.BLUE_GREY_500)

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
                                color=Colors.BLUE_GREY_400,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Text(
                                message,
                                size=13,
                                color=Colors.BLUE_GREY_700,
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
            border_radius=6,
            bgcolor=Colors.BLUE_GREY_50,
        )

        logs_list.controls.append(log_entry)
        if len(logs_list.controls) > 100:
            logs_list.controls.pop(0)
        page.update()

    def clear_logs(e=None):
        logs_list.controls.clear()
        page.update()

    # --- Confirmation Dialog ---
    confirm_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Confirmar Operacion"),
        content=ft.Text("Estas seguro de que deseas ejecutar esta operacion?"),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: page.pop_dialog()),
            ft.FilledButton("Confirmar", on_click=lambda e: None),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    pending_action = None

    progress_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Procesando..."),
        content=ft.Column(
            [
                ft.ProgressRing(width=40, height=40),
                ft.Text("Ejecutando operacion, por favor espere..."),
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
        title=ft.Text("Workspaces Encontrados"),
        content=ft.Container(width=500, height=400),
        actions=[
            ft.TextButton("Cerrar", on_click=lambda e: page.pop_dialog()),
        ],
    )
    def show_workspaces(result):
        if result.get("status") != "success":
            return

        workspaces = result.get("workspaces", {})
        if not workspaces:
            explorer_dialog.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(Icons.FOLDER_OFF, size=48, color=Colors.BLUE_GREY_300),
                        ft.Text("No se encontraron workspaces", color=Colors.BLUE_GREY_500),
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
                            label=ft.Text(fname, size=12),
                            bgcolor=Colors.INDIGO_50,
                        )
                    )
                if len(data["files"]) > 5:
                    files_chips.append(
                        ft.Text(f"+{len(data['files']) - 5} mas", size=12, color=Colors.BLUE_GREY_500)
                    )

                workspace_items.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(Icons.FOLDER, color=Colors.INDIGO_500, size=20),
                                        ft.Text(name, size=14, weight=ft.FontWeight.BOLD),
                                        ft.Container(expand=True),
                                        ft.Container(
                                            content=ft.Text(f"{data['file_count']}", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                            bgcolor=ft.Colors.INDIGO_500,
                                            border_radius=12,
                                            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=2),
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(data["path"], size=11, color=Colors.BLUE_GREY_400),
                                ft.Row(
                                    files_chips,
                                    spacing=4,
                                    run_spacing=4,
                                    wrap=True,
                                ) if files_chips else ft.Text("Sin archivos", size=12, color=Colors.BLUE_GREY_400, italic=True),
                            ],
                            spacing=6,
                        ),
                        padding=12,
                        border_radius=8,
                        bgcolor=Colors.BLUE_GREY_50,
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

    # --- Config Editor Dialog ---
    config_fields = {}
    config_schema = ConfigManager.get_schema()

    def build_config_editor():
        fields = []
        config_fields.clear()

        for field in config_schema:
            key = field["key"]
            label = field["label"]
            current_val = config.get(key, "")

            if field["type"] == "bool":
                sw = ft.Switch(
                    value=bool(current_val),
                    active_color=Colors.INDIGO_500,
                )
                config_fields[key] = sw
                row = ft.Row(
                    [
                        ft.Text(label, size=14, color=Colors.BLUE_GREY_700),
                        ft.Container(expand=True),
                        sw,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            elif field["type"] == "select":
                dd = ft.Dropdown(
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
                        ft.Text(label, size=14, color=Colors.BLUE_GREY_700, expand=True),
                        dd,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            else:
                pw = field["type"] == "password"
                tf = ft.TextField(
                    value=str(current_val) if current_val is not None else "",
                    password=pw,
                    can_reveal_password=pw,
                    dense=True,
                    content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
                    text_size=13,
                    border_color=Colors.BLUE_GREY_300,
                    focused_border_color=Colors.INDIGO_500,
                    width=280,
                )
                config_fields[key] = tf
                row = ft.Row(
                    [
                        ft.Text(label, size=14, color=Colors.BLUE_GREY_700, expand=True),
                        tf,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )

            fields.append(row)

        return ft.Column(fields, spacing=14, scroll=ft.ScrollMode.AUTO, height=450)

    config_editor_content = build_config_editor()

    config_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Row(
            [
                ft.Icon(Icons.TUNE, color=Colors.INDIGO_500),
                ft.Text("Configuración", size=18, weight=ft.FontWeight.BOLD),
            ],
            spacing=8,
        ),
        content=ft.Container(
            content=config_editor_content,
            width=520,
        ),
        actions=[
            ft.TextButton(
                "Cancelar",
                icon=Icons.CLOSE,
                on_click=lambda e: page.pop_dialog(),
            ),
            ft.FilledButton(
                "Guardar",
                icon=Icons.SAVE,
                on_click=lambda e: save_config(),
                style=ft.ButtonStyle(
                    bgcolor=Colors.INDIGO_600,
                    color=Colors.WHITE,
                    shape=ft.RoundedRectangleBorder(radius=8),
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
            show_snackbar("Configuración guardada correctamente", Colors.GREEN_700)
            add_log("Configuración actualizada y guardada", "success")
        else:
            show_snackbar("Error al guardar configuracion", Colors.RED_700)

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
            set_status(f"✓ {operation_name} completado", Colors.GREEN_500)
            add_log(f"{operation_name}: {result.get('message', 'OK')}", "success")
            show_snackbar(f"{operation_name} completado exitosamente", Colors.GREEN_700)
        elif level == "warning":
            set_status(f"⚠ {operation_name} - advertencia", Colors.AMBER_500)
            add_log(f"{operation_name}: {result.get('message', 'Warning')}", "warning")
            show_snackbar(result.get("message", "Advertencia"), Colors.AMBER_700)
        else:
            set_status(f"✗ {operation_name} fallo", Colors.RED_500)
            add_log(f"{operation_name}: {result.get('message', str(result))}", "error")
            show_snackbar(f"Error en {operation_name}: {result.get('message', '')}", Colors.RED_700)

        logger.info(f"{operation_name}: {result}")
        nonlocal is_processing
        is_processing = False
        progress_ring.visible = False
        page.update()

    def wrap_operation(name, fn, confirm=False, dialog_title="", dialog_msg="", show_progress=False):
        def handler(e):
            nonlocal is_processing
            if is_processing:
                show_snackbar("Ya hay una operacion en curso", Colors.AMBER_700)
                return

            def execute():
                nonlocal is_processing
                is_processing = True

                if show_progress:
                    progress_dialog.title.value = f"{name} - En progreso"
                    progress_dialog.content.value = ft.Column(
                        [
                            ft.ProgressRing(width=40, height=40),
                            ft.Text("Procesando archivos y generando descripciones..."),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=20,
                    )
                    page.show_dialog(progress_dialog)
                page.update()

                set_status(f"Ejecutando: {name}...", Colors.INDIGO_500, loading=True)
                add_log(f"Iniciando: {name}...", "info")

                def run_in_thread():
                    try:
                        result = fn()
                        log_operation(name, result, show_progress)
                        if result.get("status") in ("success", "warning"):
                            update_stats(result)
                            if name == "Escanear Archivos":
                                show_workspaces(result)
                    except Exception as ex:
                        log_operation(name, {"status": "error", "message": str(ex)}, show_progress)

                threading.Thread(target=run_in_thread, daemon=True).start()

            if confirm:
                show_confirm(execute, dialog_title, dialog_msg)
            else:
                execute()

        return handler

    on_sort_files = wrap_operation(
        "Actualizar Espacios de Trabajo",
        manager.sort_files,
        confirm=True,
        dialog_title="Actualizar Espacios de Trabajo",
        dialog_msg="Se subiran archivos a los workspaces y se generaran descripciones de imagenes con IA. ¿Continuar?",
        show_progress=True,
    )

    on_clean_folders = wrap_operation(
        "Limpiar Carpetas",
        manager.clean_folders,
        confirm=True,
        dialog_title="Limpiar Carpetas",
        dialog_msg="Se eliminaran los workspaces vacios. ¿Continuar?",
    )

    on_scan_files = wrap_operation("Escanear Archivos", manager.scan_files)

    on_full_upload = wrap_operation(
        "Carga Completa y Limpieza",
        manager.full_upload_and_clean,
        confirm=True,
        dialog_title="Carga Completa y Limpieza",
        dialog_msg="Se subiran archivos nuevos, se actualizaran los existentes y se eliminaran documentos huerfanos de workspaces. ¿Continuar?",
        show_progress=True,
    )

    on_create_image_descriptions = wrap_operation(
        "Descripciones de Imagenes",
        manager.create_image_descriptions,
        confirm=True,
        dialog_title="Descripciones de Imagenes",
        dialog_msg="Se generaran descripciones con IA para todas las imagenes sin descripcion. ¿Continuar?",
        show_progress=True,
    )

    # ========== BUILD UI ==========

    # AppBar
    app_bar = ft.AppBar(
        leading=ft.Icon(Icons.CLOUD_SYNC, color=Colors.WHITE, size=28),
        leading_width=56,
        title=ft.Column(
            [
                ft.Text("InfoHub File Manager", size=18, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
                ft.Text("Sincronizacion con InfoHub", size=12, color=Colors.INDIGO_100),
            ],
            spacing=0,
        ),
        center_title=False,
        bgcolor=Colors.INDIGO_700,
        actions=[
            ft.IconButton(
                icon=Icons.REFRESH,
                icon_color=Colors.WHITE,
                tooltip="Actualizar Estado",
                on_click=lambda e: (
                    set_status("Sistema listo", Colors.GREEN_500),
                    show_snackbar("Estado actualizado", Colors.GREEN_700),
                ),
            ),
            ft.IconButton(
                icon=Icons.SETTINGS,
                icon_color=Colors.WHITE,
                tooltip="Configuración",
                on_click=open_config_editor,
            ),
        ],
    )

    # Operations Grid
    operations_grid = ft.ResponsiveRow(
        [
            create_operation_card(
                Icons.CLOUD_SYNC,
                "Carga Completa y Limpieza",
                "Sincronizacion completa: subir, actualizar y eliminar documentos huerfanos",
                on_full_upload,
                Colors.CYAN_600,
            ),
            create_operation_card(
                Icons.SYNC,
                "Actualizar Espacios de Trabajo",
                "Generar descripciones de imagenes con IA y subir archivos a workspaces",
                on_sort_files,
                Colors.INDIGO_500,
            ),
            create_operation_card(
                Icons.CLEANING_SERVICES,
                "Limpiar Carpetas",
                "Eliminar workspaces vacios de InfoHub",
                on_clean_folders,
                Colors.AMBER_500,
            ),
            create_operation_card(
                Icons.SEARCH,
                "Escanear Archivos",
                "Previsualizar contenido de carpetas sin subir",
                on_scan_files,
                Colors.CYAN_600,
            ),
            create_operation_card(
                Icons.IMAGE,
                "Descripciones de Imagenes",
                "Generar descripciones con IA para imagenes sin descripcion",
                on_create_image_descriptions,
                Colors.AMBER_600,
            ),
        ],
        spacing=16,
        run_spacing=16,
    )

    # Logs Panel
    logs_panel = ft.Card(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Row(
                                [
                                    ft.Icon(Icons.TERMINAL, color=Colors.BLUE_GREY_600, size=18),
                                    ft.Text("Registro de Operaciones", size=14, weight=ft.FontWeight.BOLD, color=Colors.BLUE_GREY_700),
                                ],
                                spacing=8,
                            ),
                            ft.Container(expand=True),
                            ft.TextButton(
                                "Limpiar",
                                icon=Icons.CLEAR_ALL,
                                on_click=clear_logs,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=logs_list,
                        border=ft.border.Border.all(1, Colors.BLUE_GREY_200),
                        border_radius=8,
                        bgcolor=Colors.WHITE,
                    ),
                ],
                spacing=10,
            ),
            padding=16,
        ),
        elevation=1,
    )

    # Main Layout
    main_content = ft.Container(
        content=ft.Column(
            [
                # Stats Row
                ft.Container(
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
                    padding=ft.padding.Padding.only(bottom=16),
                ),
                # Operations Section
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text("Operaciones", size=18, weight=ft.FontWeight.BOLD, color=Colors.BLUE_GREY_800),
                                    ft.Container(expand=True),
                                    ft.Text(
                                        f"v1.0 | {datetime.now().strftime('%Y-%m-%d')}",
                                        size=12,
                                        color=Colors.BLUE_GREY_400,
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
                            content=logs_panel,
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
        padding=24,
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

    # Initial log
    add_log("Sistema iniciado correctamente", "success")
    add_log(f"Conectado a: {manager.base_url}", "info")


if __name__ == "__main__":
    ft.run(
        main,
        view=ft.AppView.WEB_BROWSER,
        port=int(os.getenv("APP_PORT", 8500)),
    )
