"""
InfoHub File Manager - Flet Web Dashboard
Panel de control para sincronizar archivos con AnythingLLM/InfoHub
"""

import os
import base64
import logging
import requests
from pathlib import Path
from datetime import datetime

import flet as ft
from flet import Icons, Colors
from dotenv import load_dotenv

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


class InfoHubFileManager:
    """Manages file synchronization with AnythingLLM/InfoHub"""

    def __init__(self):
        self.api_key = os.getenv("ANYTHINGLLM_API_KEY")
        self.base_url = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3000")
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llava:latest")
        self.image_description_active = (
            os.getenv("IMAGE_DESCRIPTION_ACTIVATE", "true").lower() == "true"
        )
        self.watched_root = os.getenv("WATCHED_FOLDERS_ROOT")

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
        total_files = 0
        for item in root_path.iterdir():
            if item.is_dir() and (
                item.name.startswith("Infohub") or item.name.startswith("AnythingLLM")
            ):
                for workspace_folder in item.iterdir():
                    if workspace_folder.is_dir():
                        files = list(workspace_folder.iterdir())
                        file_names = [
                            f.name
                            for f in files
                            if f.is_file()
                            and not f.name.endswith(".image_description")
                            and not f.name.endswith(".image_description.txt")
                        ]
                        workspaces[workspace_folder.name] = {
                            "path": str(workspace_folder),
                            "file_count": len(file_names),
                            "files": file_names,
                        }
                        total_files += len(file_names)

        return {
            "status": "success",
            "workspaces": workspaces,
            "total_workspaces": len(workspaces),
            "total_files": total_files,
        }

    def get_workspace_slug(self, workspace_name: str) -> str:
        """Convert workspace name to slug format"""
        return workspace_name.lower().replace(" ", "-").replace("_", "-")

    def get_workspace_documents(self, workspace_name: str) -> set:
        """Get set of document filenames already in workspace"""
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
                    if isinstance(workspace, list) and len(workspace) > 0:
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

                # Extract filenames from docpath
                filenames = set()
                for doc in documents:
                    if isinstance(doc, dict):
                        docpath = doc.get("docpath", "")
                        if docpath:
                            filenames.add(docpath.split("/")[-1].replace(".json", ""))
                return filenames
            else:
                logger.warning(
                    f"Failed to get workspace documents: {response.status_code}"
                )
                return set()
        except Exception as e:
            logger.error(f"Error getting workspace documents: {e}")
            return set()

    def file_exists_in_workspace(self, file_path: Path, workspace_name: str) -> bool:
        """Check if file already exists in workspace"""
        existing_docs = self.get_workspace_documents(workspace_name)
        # Check by filename without extension
        filename_without_ext = file_path.stem
        return filename_without_ext in existing_docs

    def upload_file_to_workspace(
        self, file_path: Path, workspace_name: str, skip_if_exists: bool = True
    ) -> tuple:
        """Upload a single file to AnythingLLM workspace

        Returns:
            tuple: (success: bool, skipped: bool, message: str)
        """
        try:
            # Check if file already exists
            if skip_if_exists and self.file_exists_in_workspace(
                file_path, workspace_name
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
                files = {"file": (file_path.name, f)}
                response = requests.post(url, headers=headers, files=files, timeout=30)

            if response.status_code in (200, 201):
                logger.info(f"Uploaded {file_path.name} to {workspace_name}")
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
        """Sort files into appropriate workspaces"""
        try:
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
            for item in root_path.iterdir():
                if item.is_dir() and (
                    item.name.startswith("Infohub")
                    or item.name.startswith("AnythingLLM")
                ):
                    for workspace_folder in item.iterdir():
                        if workspace_folder.is_dir():
                            for file_path in workspace_folder.iterdir():
                                if (
                                    file_path.is_file()
                                    and not file_path.name.endswith(
                                        ".image_description"
                                    )
                                    and not file_path.name.endswith(
                                        ".image_description.txt"
                                    )
                                ):
                                    success, was_skipped, msg = (
                                        self.upload_file_to_workspace(
                                            file_path, workspace_folder.name
                                        )
                                    )
                                    if success:
                                        uploaded += 1
                                    elif was_skipped:
                                        skipped += 1

            return {
                "status": "success",
                "message": f"Proceso completado: {uploaded} subidos, {skipped} omitidos (ya existian)",
                "uploaded": uploaded,
                "skipped": skipped,
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
            workspaces_processed = 0

            for item in root_path.iterdir():
                if item.is_dir() and (
                    item.name.startswith("Infohub")
                    or item.name.startswith("AnythingLLM")
                ):
                    for workspace_folder in item.iterdir():
                        if workspace_folder.is_dir():
                            workspaces_processed += 1
                            for file_path in workspace_folder.iterdir():
                                if (
                                    file_path.is_file()
                                    and not file_path.name.endswith(
                                        ".image_description"
                                    )
                                    and not file_path.name.endswith(
                                        ".image_description.txt"
                                    )
                                ):
                                    success, was_skipped, msg = (
                                        self.upload_file_to_workspace(
                                            file_path, workspace_folder.name
                                        )
                                    )
                                    if success:
                                        uploaded += 1
                                    elif was_skipped:
                                        skipped += 1

            return {
                "status": "success",
                "message": f"{workspaces_processed} workspaces procesados, {uploaded} archivos subidos, {skipped} omitidos",
                "workspaces_processed": workspaces_processed,
                "uploaded": uploaded,
                "skipped": skipped,
            }
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

        logger.info(
            f"Sending {image_path.name} to Ollama Cloud ({self.ollama_model})..."
        )
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

        image_extensions = {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".webp",
            ".tiff",
            ".tif",
        }
        processed = 0
        skipped = 0
        errors = []

        # Collect all images first for better logging
        images_to_process = []
        for item in root_path.iterdir():
            if item.is_dir() and (
                item.name.startswith("Infohub") or item.name.startswith("AnythingLLM")
            ):
                for workspace_folder in item.iterdir():
                    if workspace_folder.is_dir():
                        for file_path in workspace_folder.iterdir():
                            if (
                                file_path.is_file()
                                and file_path.suffix.lower() in image_extensions
                            ):
                                desc_file = file_path.with_suffix(
                                    ".image_description.txt"
                                )
                                if desc_file.exists():
                                    skipped += 1
                                else:
                                    images_to_process.append(file_path)

        total_images = len(images_to_process) + skipped
        logger.info(
            f"Found {total_images} images: {len(images_to_process)} to process, {skipped} already have descriptions"
        )

        if not images_to_process:
            return {
                "status": "success",
                "message": f"Todas las {skipped} imagenes ya tienen descripciones",
                "processed": 0,
                "skipped": skipped,
            }

        for idx, file_path in enumerate(images_to_process, 1):
            desc_file = file_path.with_suffix(".image_description.txt")
            logger.info(
                f"[{idx}/{len(images_to_process)}] Processing {file_path.name}..."
            )

            try:
                description = self._generate_image_description(file_path)

                with open(desc_file, "w", encoding="utf-8") as f:
                    f.write(description)

                logger.info(
                    f"[{idx}/{len(images_to_process)}] Created description for {file_path.name}"
                )
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
    # ========== PAGE CONFIGURATION ==========
    page.title = os.getenv("APP_TITLE", "InfoHub File Manager")
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0
    page.spacing = 0

    # Custom theme colors
    page.theme = ft.Theme(
        color_scheme_seed="#2563EB",
        use_material3=True,
    )

    manager = InfoHubFileManager()

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
        bgcolor=Colors.GREY_800,
        duration=4000,
    )
    page.overlay.append(snackbar)

    def show_snackbar(message, color=Colors.GREY_800):
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
                                    color=Colors.GREY_800,
                                ),
                                ft.Text(
                                    label,
                                    size=12,
                                    color=Colors.GREY_500,
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

    workspaces_stat = create_stat_card(
        "0", "Workspaces", Icons.FOLDER_COPY, Colors.BLUE_500
    )
    files_stat = create_stat_card("0", "Archivos", Icons.DESCRIPTION, Colors.GREEN_500)
    uploaded_stat = create_stat_card(
        "0", "Subidos", Icons.CLOUD_UPLOAD, Colors.PURPLE_500
    )
    pending_stat = create_stat_card(
        "0", "Pendientes", Icons.SCHEDULE, Colors.ORANGE_500
    )

    def update_stats(scan_result=None):
        if scan_result and scan_result.get("status") == "success":
            workspaces_stat.content.content.controls[1].controls[0].value = str(
                scan_result.get("total_workspaces", 0)
            )
            files_stat.content.content.controls[1].controls[0].value = str(
                scan_result.get("total_files", 0)
            )
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
        size=13,
        weight=ft.FontWeight.W_500,
        color=Colors.GREY_700,
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
        bgcolor=Colors.GREY_50,
        border=ft.border.Border.only(bottom=ft.border.BorderSide(1, Colors.GREY_200)),
    )

    def set_status(text, color=Colors.GREEN_500, loading=False):
        status_indicator.bgcolor = color
        status_text.value = text
        progress_ring.visible = loading
        page.update()

    # --- Operation Cards ---
    def create_operation_card(
        icon, title, description, on_click, color, badge_text=None
    ):
        badge = None
        if badge_text:
            badge = ft.Container(
                content=ft.Text(
                    badge_text, size=10, weight=ft.FontWeight.BOLD, color=Colors.WHITE
                ),
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
                            color=Colors.GREY_800,
                        ),
                        ft.Text(
                            description,
                            size=12,
                            color=Colors.GREY_500,
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
                                padding=ft.padding.Padding.symmetric(
                                    horizontal=16, vertical=10
                                ),
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
            "info": Colors.BLUE_500,
            "success": Colors.GREEN_500,
            "warning": Colors.ORANGE_500,
            "error": Colors.RED_500,
        }.get(level, Colors.GREY_500)

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
                                size=10,
                                color=Colors.GREY_400,
                                weight=ft.FontWeight.W_500,
                            ),
                            ft.Text(
                                message,
                                size=12,
                                color=Colors.GREY_700,
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
            bgcolor=Colors.GREY_50,
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
            ft.TextButton(
                "Cancelar",
                on_click=lambda e: (
                    setattr(confirm_dialog, "open", False) or page.update()
                ),
            ),
            ft.FilledButton("Confirmar", on_click=lambda e: None),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(confirm_dialog)

    pending_action = None

    def show_confirm(action, title, message):
        nonlocal pending_action
        pending_action = action
        confirm_dialog.title.value = title
        confirm_dialog.content.value = message
        confirm_dialog.actions[1].on_click = lambda e: (
            setattr(confirm_dialog, "open", False),
            action(),
            page.update(),
        )
        confirm_dialog.open = True
        page.update()

    # --- Workspace Explorer Dialog ---
    explorer_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Workspaces Encontrados"),
        content=ft.Container(width=500, height=400),
        actions=[
            ft.TextButton(
                "Cerrar",
                on_click=lambda e: (
                    setattr(explorer_dialog, "open", False) or page.update()
                ),
            ),
        ],
    )
    page.overlay.append(explorer_dialog)

    def show_workspaces(result):
        if result.get("status") != "success":
            return

        workspaces = result.get("workspaces", {})
        if not workspaces:
            explorer_dialog.content = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(Icons.FOLDER_OFF, size=48, color=Colors.GREY_300),
                        ft.Text("No se encontraron workspaces", color=Colors.GREY_500),
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
                            label=ft.Text(fname, size=11),
                            bgcolor=Colors.BLUE_50,
                        )
                    )
                if len(data["files"]) > 5:
                    files_chips.append(
                        ft.Text(
                            f"+{len(data['files']) - 5} mas",
                            size=11,
                            color=Colors.GREY_500,
                        )
                    )

                workspace_items.append(
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Icon(
                                            Icons.FOLDER, color=Colors.BLUE_500, size=20
                                        ),
                                        ft.Text(
                                            name, size=14, weight=ft.FontWeight.BOLD
                                        ),
                                        ft.Container(expand=True),
                                        ft.Container(
                                            content=ft.Text(
                                                f"{data['file_count']}",
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=Colors.WHITE,
                                            ),
                                            bgcolor=Colors.BLUE_700,
                                            padding=8,
                                            border_radius=10,
                                        ),
                                    ],
                                    spacing=8,
                                ),
                                ft.Text(data["path"], size=10, color=Colors.GREY_400),
                                ft.Row(
                                    files_chips,
                                    spacing=4,
                                    run_spacing=4,
                                    wrap=True,
                                )
                                if files_chips
                                else ft.Text(
                                    "Sin archivos",
                                    size=11,
                                    color=Colors.GREY_400,
                                    italic=True,
                                ),
                            ],
                            spacing=6,
                        ),
                        padding=12,
                        border_radius=8,
                        bgcolor=Colors.GREY_50,
                        margin=ft.margin.Margin.only(bottom=8),
                    )
                )

            explorer_dialog.content = ft.Column(
                workspace_items,
                scroll=ft.ScrollMode.AUTO,
                spacing=0,
                height=400,
            )

        explorer_dialog.open = True
        page.update()

    # ========== OPERATION HANDLERS ==========

    def log_operation(operation_name: str, result: dict):
        """Log operation result and update UI"""
        level = result.get("status", "info")

        if level == "success":
            set_status(f"✓ {operation_name} completado", Colors.GREEN_500)
            add_log(f"{operation_name}: {result.get('message', 'OK')}", "success")
            show_snackbar(f"{operation_name} completado exitosamente", Colors.GREEN_700)
        elif level == "warning":
            set_status(f"⚠ {operation_name} - advertencia", Colors.ORANGE_500)
            add_log(f"{operation_name}: {result.get('message', 'Warning')}", "warning")
            show_snackbar(result.get("message", "Advertencia"), Colors.ORANGE_700)
        else:
            set_status(f"✗ {operation_name} fallo", Colors.RED_500)
            add_log(f"{operation_name}: {result.get('message', str(result))}", "error")
            show_snackbar(
                f"Error en {operation_name}: {result.get('message', '')}",
                Colors.RED_700,
            )

        logger.info(f"{operation_name}: {result}")
        nonlocal is_processing
        is_processing = False
        progress_ring.visible = False
        page.update()

    def wrap_operation(name, fn, confirm=False, dialog_title="", dialog_msg=""):
        def handler(e):
            nonlocal is_processing
            if is_processing:
                show_snackbar("Ya hay una operacion en curso", Colors.ORANGE_700)
                return

            def execute():
                import threading
                import asyncio

                async def run_async():
                    nonlocal is_processing
                    try:
                        if asyncio.iscoroutinefunction(fn):
                            result = await fn()
                        else:
                            result = fn()
                        log_operation(name, result)
                        if name == "Escanear Archivos":
                            update_stats(result)
                            show_workspaces(result)
                    except Exception as ex:
                        log_operation(name, {"status": "error", "message": str(ex)})
                    finally:
                        is_processing = False
                        set_status("Sistema listo", Colors.GREEN_500)

                is_processing = True
                set_status(f"Ejecutando: {name}...", Colors.BLUE_500, loading=True)
                add_log(f"Iniciando: {name}...", "info")

                page.run_task(run_async)

            if confirm:
                show_confirm(execute, dialog_title, dialog_msg)
            else:
                execute()

        return handler

    on_full_upload = wrap_operation(
        "Carga Completa y Limpieza",
        manager.full_upload_and_clean,
        confirm=True,
        dialog_title="Carga Completa y Limpieza",
        dialog_msg="Se subiran los archivos nuevos y se limpiaran los eliminados. ¿Continuar?",
    )

    on_sort_files = wrap_operation(
        "Ordenar Archivos",
        manager.sort_files,
        confirm=True,
        dialog_title="Ordenar Archivos",
        dialog_msg="Se organizaran los archivos en sus workspaces correspondientes. ¿Continuar?",
    )

    on_clean_folders = wrap_operation(
        "Limpiar Carpetas",
        manager.clean_folders,
        confirm=True,
        dialog_title="Limpiar Carpetas",
        dialog_msg="Se eliminaran los workspaces vacios. ¿Continuar?",
    )

    on_scan_files = wrap_operation("Escanear Archivos", manager.scan_files)

    on_create_descriptions = wrap_operation(
        "Crear Descripciones de Imagenes",
        manager.create_image_descriptions,
        confirm=True,
        dialog_title="Generar Descripciones con IA",
        dialog_msg="Se generaran descripciones para todas las imagenes usando Ollama. Este proceso puede tardar. ¿Continuar?",
    )

    # ========== BUILD UI ==========

    # AppBar
    app_bar = ft.AppBar(
        leading=ft.Icon(Icons.CLOUD_SYNC, color=Colors.WHITE, size=28),
        leading_width=56,
        title=ft.Column(
            [
                ft.Text(
                    "InfoHub File Manager",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=Colors.WHITE,
                ),
                ft.Text(
                    "Sincronizacion con AnythingLLM", size=11, color=Colors.BLUE_100
                ),
            ],
            spacing=0,
        ),
        center_title=False,
        bgcolor=Colors.BLUE_700,
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
                tooltip="Configuracion",
                on_click=lambda e: show_snackbar(
                    f"API: {manager.base_url} | Ollama: {manager.ollama_url}",
                    Colors.BLUE_700,
                ),
            ),
        ],
    )

    # Operations Grid
    operations_grid = ft.ResponsiveRow(
        [
            create_operation_card(
                Icons.UPLOAD_FILE,
                "Carga Completa",
                "Escanear carpetas, subir archivos nuevos/modificados y eliminar los eliminados",
                on_full_upload,
                Colors.BLUE_500,
            ),
            create_operation_card(
                Icons.FOLDER_SHARED,
                "Ordenar Archivos",
                "Organizar automaticamente documentos en las carpetas de workspace correctas",
                on_sort_files,
                Colors.GREEN_500,
            ),
            create_operation_card(
                Icons.CLEANING_SERVICES,
                "Limpiar Carpetas",
                "Eliminar workspaces vacios de InfoHub",
                on_clean_folders,
                Colors.ORANGE_500,
            ),
            create_operation_card(
                Icons.SEARCH,
                "Escanear Archivos",
                "Previsualizar contenido de carpetas sin subir",
                on_scan_files,
                Colors.PURPLE_500,
            ),
            create_operation_card(
                Icons.IMAGE,
                "Descripciones IA",
                "Generar descripciones con IA para imagenes (requiere Ollama)",
                on_create_descriptions,
                Colors.PINK_500,
                badge_text="IA",
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
                                    ft.Icon(
                                        Icons.TERMINAL, color=Colors.GREY_600, size=18
                                    ),
                                    ft.Text(
                                        "Registro de Operaciones",
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color=Colors.GREY_700,
                                    ),
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
                        border=ft.border.Border.all(1, Colors.GREY_200),
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

    # Config Panel
    config_items = [
        ft.Row(
            [
                ft.Icon(Icons.LINK, size=16, color=Colors.BLUE_500),
                ft.Column(
                    [
                        ft.Text(
                            "API URL",
                            size=11,
                            color=Colors.GREY_500,
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Text(manager.base_url, size=13, color=Colors.GREY_800),
                    ],
                    spacing=0,
                ),
            ],
            spacing=12,
        ),
        ft.Row(
            [
                ft.Icon(Icons.MODEL_TRAINING, size=16, color=Colors.PURPLE_500),
                ft.Column(
                    [
                        ft.Text(
                            "Ollama",
                            size=11,
                            color=Colors.GREY_500,
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Text(
                            f"{manager.ollama_url} ({manager.ollama_model})",
                            size=13,
                            color=Colors.GREY_800,
                        ),
                    ],
                    spacing=0,
                ),
            ],
            spacing=12,
        ),
        ft.Row(
            [
                ft.Icon(Icons.FOLDER_OPEN, size=16, color=Colors.GREEN_500),
                ft.Column(
                    [
                        ft.Text(
                            "Raiz Observada",
                            size=11,
                            color=Colors.GREY_500,
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Text(
                            manager.watched_root or "No configurado",
                            size=13,
                            color=Colors.GREY_800,
                        ),
                    ],
                    spacing=0,
                ),
            ],
            spacing=12,
        ),
        ft.Row(
            [
                ft.Icon(Icons.IMAGE, size=16, color=Colors.PINK_500),
                ft.Column(
                    [
                        ft.Text(
                            "Descripciones de Imagenes",
                            size=11,
                            color=Colors.GREY_500,
                            weight=ft.FontWeight.W_500,
                        ),
                        ft.Text(
                            "Habilitado"
                            if manager.image_description_active
                            else "Deshabilitado",
                            size=13,
                            color=Colors.GREEN_700
                            if manager.image_description_active
                            else Colors.RED_700,
                        ),
                    ],
                    spacing=0,
                ),
            ],
            spacing=12,
        ),
    ]

    config_panel = ft.Card(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(Icons.SETTINGS, color=Colors.GREY_600, size=18),
                            ft.Text(
                                "Configuracion",
                                size=14,
                                weight=ft.FontWeight.BOLD,
                                color=Colors.GREY_700,
                            ),
                        ],
                        spacing=8,
                    ),
                    ft.Divider(height=1, color=Colors.GREY_200),
                    ft.Column(config_items, spacing=12),
                ],
                spacing=12,
            ),
            padding=16,
        ),
        elevation=1,
        col={"xs": 12, "sm": 12, "md": 4, "lg": 4, "xl": 4},
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
                                    ft.Text(
                                        "Operaciones",
                                        size=18,
                                        weight=ft.FontWeight.BOLD,
                                        color=Colors.GREY_800,
                                    ),
                                    ft.Container(expand=True),
                                    ft.Text(
                                        f"v1.0 | {datetime.now().strftime('%Y-%m-%d')}",
                                        size=11,
                                        color=Colors.GREY_400,
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
                # Logs and Config Row
                ft.ResponsiveRow(
                    [
                        ft.Container(
                            content=logs_panel,
                            col={"xs": 12, "sm": 12, "md": 8, "lg": 8, "xl": 8},
                        ),
                        config_panel,
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
        port=int(os.getenv("APP_PORT", 8000)),
    )
