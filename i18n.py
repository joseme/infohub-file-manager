"""Textos de la interfaz en español e inglés.

Misma regla que InfoHub, Infohub Chat y el DMS: la elección del usuario (en
ese navegador o equipo); si no eligió, el idioma de la instancia de InfoHub
(GET /api/system/instance-language); si nada responde, español.

El idioma es de cada sesión: en la versión web varias sesiones comparten el
proceso, así que no hay un idioma global. Cada sesión usa su `Translator`.
ES es la fuente; tests/i18n_test.py comprueba que EN tenga las mismas claves y
los mismos campos de formato.
"""

from __future__ import annotations

import requests

SUPPORTED = ("es", "en")
DEFAULT = "es"
ENDONYMS = {"es": "Español", "en": "English"}

# Preferencias del usuario (page.shared_preferences). assets/tour/tour.js las
# lee del localStorage de Flutter web.
PREF_LANGUAGE = "infohubFm.language"
PREF_INSTANCE_LANGUAGE = "infohubFm.instanceLanguage"

ES: dict[str, str] = {
    # --- general ---
    "common.cancel": "Cancelar",
    "common.close": "Cerrar",
    "common.accept": "Aceptar",
    "common.save": "Guardar",
    "common.confirm": "Confirmar",
    "common.run": "Ejecutar",
    "common.error": "Error: {error}",
    "common.language": "Idioma",
    "common.user": "usuario",
    # --- inicio de sesión ---
    "login.title": "Iniciar sesión en InfoHub",
    "login.intro": "Accede con tu usuario y contraseña de InfoHub. Solo verás los workspaces que tienes habilitados.",
    "login.url": "URL InfoHub",
    "login.username": "Usuario",
    "login.password": "Contraseña",
    "login.submit": "Ingresar",
    "login.backHome": "Volver al inicio",
    "login.exit": "Salir",
    "login.required": "URL, usuario y contraseña son obligatorios",
    "login.invalid": "Credenciales inválidas",
    "login.badConfig": "config.json no es válido: {error}. Se están usando valores por defecto.",
    "login.ssoFailed": "No se pudo iniciar sesión desde el portal (enlace vencido o usado). Ingresa tus credenciales.",
    "login.ssoFailedLog": "Inicio de sesión desde el portal falló: {error}",
    "login.signedIn": "Sesión iniciada como {user}",
    "login.signedInLog": "Inicio de sesión correcto (usuario: {user}). Workspaces habilitados: {count}",
    "login.noApiKey": "API Key de InfoHub ausente o inválida en config.json: la sincronización fallará hasta configurarla",
    "login.noApiKeyLog": "Advertencia: API Key de InfoHub ausente o inválida. Configúrala en Ajustes para poder sincronizar.",
    "workspaces.title": "Tus workspaces habilitados",
    "workspaces.none": "No tienes workspaces habilitados.",
    # --- barra superior y estado ---
    "bar.home": "Volver al inicio de InfoHub",
    "bar.refresh": "Actualizar estado",
    "bar.settings": "Configuración",
    "bar.tour": "Ver recorrido",
    "status.ready": "Sistema listo",
    "status.refreshed": "Estado actualizado",
    "status.running": "Ejecutando: {name}...",
    "status.done": "✓ {name} completado",
    "status.warning": "⚠ {name}: advertencia",
    "status.failed": "✗ {name} falló",
    "stats.workspaces": "Workspaces",
    "stats.files": "Archivos",
    "stats.uploaded": "Subidos",
    "stats.pending": "Pendientes",
    # --- operaciones ---
    "ops.title": "Operaciones",
    "ops.busy": "Ya hay una operación en curso",
    "ops.inProgress": "{name}: en progreso",
    "ops.processingFiles": "Procesando archivos y generando descripciones...",
    "ops.starting": "Iniciando: {name}...",
    "ops.doneSnack": "{name} completado",
    "ops.warning": "Advertencia",
    "ops.errorSnack": "Error en {name}: {message}",
    "ops.full.title": "Carga completa y limpieza",
    "ops.full.description": "Sincronización completa: subir, actualizar y eliminar documentos huérfanos",
    "ops.full.confirm": "Se subirán archivos nuevos, se actualizarán los existentes y se eliminarán documentos huérfanos de los workspaces. ¿Continuar?",
    "ops.simulate.title": "Simular limpieza",
    "ops.simulate.description": "Ver qué borraría y qué subiría la carga completa, sin cambiar nada",
    "ops.sort.title": "Actualizar workspaces",
    "ops.sort.description": "Generar descripciones de imágenes con IA y subir archivos a los workspaces",
    "ops.sort.confirm": "Se subirán archivos a los workspaces y se generarán descripciones de imágenes con IA. ¿Continuar?",
    "ops.clean.title": "Limpiar carpetas",
    "ops.clean.description": "Eliminar workspaces vacíos de InfoHub",
    "ops.clean.confirm": "Se eliminarán los workspaces vacíos. ¿Continuar?",
    "ops.scan.title": "Escanear archivos",
    "ops.scan.description": "Previsualizar el contenido de las carpetas sin subir nada",
    "ops.images.title": "Descripciones de imágenes",
    "ops.images.description": "Generar descripciones con IA para las imágenes que no tienen",
    "ops.images.confirm": "Se generarán descripciones con IA para todas las imágenes sin descripción. ¿Continuar?",
    "ops.demoSync.title": "Sincronizar",
    "ops.demoSync.confirm": "Se subirán los archivos nuevos de tus subcarpetas y se quitarán de InfoHub los que borraste. ¿Continuar?",
    "ops.demoSimulate.title": "Simular sincronización",
    # --- diálogos ---
    "confirm.title": "Confirmar operación",
    "confirm.body": "¿Seguro que quieres ejecutar esta operación?",
    "progress.title": "Procesando...",
    "progress.body": "Ejecutando la operación, espera por favor...",
    "logs.title": "Registro de operaciones",
    "logs.clear": "Limpiar",
    "logs.started": "Sistema iniciado correctamente",
    "logs.connected": "Conectado a: {url} (funciones: {features})",
    "logs.noFeatures": "ninguna",
    "scan.title": "Workspaces encontrados",
    "scan.none": "No se encontraron workspaces",
    "scan.more": "+{count} más",
    "scan.noFiles": "Sin archivos",
    "simulation.titleClean": "Simulación de limpieza",
    "simulation.titleSync": "Simulación de la sincronización",
    "simulation.none": "{title}: ninguno",
    "simulation.count": "{title} ({count})",
    "simulation.more": "+{count} más (lista completa en el log)",
    "simulation.wouldCreate": " · se crearía",
    "simulation.blocked": "⚠ Borrado bloqueado: {reason}",
    "simulation.notDeleted": "No se borrarán (bloqueado)",
    "simulation.wouldDelete": "Se borrarían",
    "simulation.wouldUpload": "Se subirían",
    "simulation.noQuota": "No entran en el cupo",
    # --- configuración ---
    "config.title": "Configuración",
    "config.saved": "Configuración guardada correctamente",
    "config.savedLog": "Configuración actualizada y guardada",
    "config.saveFailed": "Error al guardar la configuración",
    "config.field.app_title": "Título de la app",
    "config.field.app_port": "Puerto",
    "config.field.anythingllm_api_key": "API Key de InfoHub",
    "config.field.anythingllm_base_url": "URL InfoHub",
    "config.field.ollama_base_url": "URL Ollama",
    "config.field.ollama_model": "Modelo Ollama",
    "config.field.image_description_active": "Descripciones de imágenes",
    "config.field.watched_folders_root": "Carpeta raíz observada",
    "config.field.protected_workspaces": "Workspaces protegidos (separados por coma)",
    "config.field.log_level": "Nivel de log",
    "config.field.log_file": "Archivo de log",
    # --- modo demo ---
    "demo.title": "Tu demo de {company}",
    "demo.expiresToday": "Vence hoy",
    "demo.oneDayLeft": "Queda 1 día",
    "demo.daysLeft": "Quedan {days} días",
    "demo.quota": "{days} · Documentos: {used} de {max} · Espacio: {usedSpace} de {maxSpace}",
    "demo.docsInInfohub.one": "1 documento en InfoHub",
    "demo.docsInInfohub.other": "{count} documentos en InfoHub",
    "demo.steps": "1. Elige una carpeta de tu equipo: se crea una subcarpeta por workspace. "
                  "2. Copia cada documento en la subcarpeta que le corresponda. "
                  "3. Sincroniza. Para quitar un documento, bórralo de la carpeta y vuelve a sincronizar.",
    "demo.folder": "Carpeta de la demo",
    "demo.folderHint": "Elige una carpeta o escribe su ruta",
    "demo.chooseFolder": "Elegir carpeta",
    "demo.chooseFolderTitle": "Elige la carpeta para tu demo",
    "demo.sync": "Sincronizar",
    "demo.simulate": "Simular",
    "demo.folderFailed": "No se pudo usar esa carpeta: {error}",
    "demo.folderLog": "Carpeta de la demo: {path}. Subcarpetas: {folders}",
    "demo.folderReady": "Listo: copia tus documentos en las subcarpetas y sincroniza",
    "demo.noPicker": "Si no se abrió el selector, escribe la ruta de la carpeta y presiona Enter",
    "demo.modeLog": "Modo demo: {count} workspaces de {company}",
    "demo.desktopOnly": "Las demos se cargan con el File Manager de escritorio, que trabaja con las "
                        "carpetas de tu equipo. Descárgalo desde «Mi demo» en InfoHub Chat.",
    "demo.readFailed": "No se pudo leer tu demo en InfoHub.",
    "demo.chooseFirst": "Elige primero la carpeta de la demo.",
    "demo.timeout": "InfoHub tardó demasiado. Vuelve a sincronizar en unos minutos para comprobarlo.",
    "demo.status": "InfoHub respondió {status}",
    "demo.simulation": "Simulación, no se cambió nada: se quitarían {deleted} documentos y se subirían {uploaded} archivos.",
    "demo.simulationNoQuota": " {count} no entran en el cupo de la demo.",
    "demo.syncResult": "{uploaded} subidos, {deleted} quitados",
    "demo.syncNoQuota": ", {count} no entran en el cupo ({names})",
    "demo.syncErrors": ", {count} con error: {errors}",
    # --- resultados de las operaciones ---
    "result.noWorkspaces": "No se pudieron obtener los workspaces del usuario",
    "result.connection": "Error de conexión con InfoHub: {error}",
    "result.rootNotConfigured": "La carpeta raíz observada no está configurada (WATCHED_FOLDERS_ROOT)",
    "result.rootMissing": "La carpeta raíz no existe: {path}",
    "result.sorted": "Archivos: {uploaded} subidos, {skipped} omitidos. Imágenes: {described} descritas, {existing} ya tenían descripción.",
    "result.protected": " Protegidos, sin tocar: {names}.",
    "result.emptyCleaned": "Carpetas vacías limpiadas",
    "result.simulation": "Simulación, no se cambió nada: se borrarían {deleted} documentos huérfanos "
                         "en {workspaces} workspaces y se subirían {uploaded} archivos ({checked} workspaces revisados).",
    "result.blocked": " Borrado bloqueado por seguridad en {count} workspaces: {names}.",
    "result.full": "{processed} workspaces procesados, {uploaded} subidos, {skipped} omitidos, {deleted} eliminados",
    "result.fullDeleteErrors": ", {count} errores al eliminar",
    "result.fullProtected": ". Protegidos, sin tocar: {names}",
    "result.fullBlocked": ". Borrado bloqueado por seguridad en {count} workspaces: {details}",
    "result.deleteUnconfirmed": "No se pudo confirmar el borrado de {name}",
    "result.imagesDisabled": "Las descripciones de imágenes están desactivadas en la configuración",
    "result.imagesAllDone": "Las {count} imágenes ya tienen descripción",
    "result.imagesDone": "{processed} descripciones creadas, {skipped} omitidas",
    "result.imagesErrors": "{processed} descripciones creadas, {skipped} omitidas, {errors} errores",
    # --- guardas del borrado (sync_guards.py) ---
    "guard.unmounted": "la carpeta está en montajes_requeridos y no está montada",
    "guard.emptyFolder": "la carpeta local está vacía y se borrarían {orphans} documentos (¿montaje caído o disco desconectado?)",
    "guard.threshold": "se borrarían {orphans} de {remote} documentos ({pct} %), más del umbral de {limit} %",
    "guard.noRoot": "no existe la carpeta raíz {root}",
    "guard.rootInaccessible": "la carpeta raíz {root} no es accesible ({error})",
}

EN: dict[str, str] = {
    "common.cancel": "Cancel",
    "common.close": "Close",
    "common.accept": "OK",
    "common.save": "Save",
    "common.confirm": "Confirm",
    "common.run": "Run",
    "common.error": "Error: {error}",
    "common.language": "Language",
    "common.user": "user",
    "login.title": "Sign in to InfoHub",
    "login.intro": "Sign in with your InfoHub username and password. You will only see the workspaces enabled for you.",
    "login.url": "InfoHub URL",
    "login.username": "Username",
    "login.password": "Password",
    "login.submit": "Sign in",
    "login.backHome": "Back to home",
    "login.exit": "Exit",
    "login.required": "URL, username and password are required",
    "login.invalid": "Invalid credentials",
    "login.badConfig": "config.json is not valid: {error}. Default values are being used.",
    "login.ssoFailed": "Signing in from the portal failed (the link expired or was already used). Enter your credentials.",
    "login.ssoFailedLog": "Sign-in from the portal failed: {error}",
    "login.signedIn": "Signed in as {user}",
    "login.signedInLog": "Signed in (user: {user}). Enabled workspaces: {count}",
    "login.noApiKey": "InfoHub API key missing or invalid in config.json: syncing will fail until it is set",
    "login.noApiKeyLog": "Warning: InfoHub API key missing or invalid. Set it in Settings to be able to sync.",
    "workspaces.title": "Your enabled workspaces",
    "workspaces.none": "You have no enabled workspaces.",
    "bar.home": "Back to the InfoHub home",
    "bar.refresh": "Refresh status",
    "bar.settings": "Settings",
    "bar.tour": "Take the tour",
    "status.ready": "System ready",
    "status.refreshed": "Status refreshed",
    "status.running": "Running: {name}...",
    "status.done": "✓ {name} completed",
    "status.warning": "⚠ {name}: warning",
    "status.failed": "✗ {name} failed",
    "stats.workspaces": "Workspaces",
    "stats.files": "Files",
    "stats.uploaded": "Uploaded",
    "stats.pending": "Pending",
    "ops.title": "Operations",
    "ops.busy": "An operation is already running",
    "ops.inProgress": "{name}: in progress",
    "ops.processingFiles": "Processing files and generating descriptions...",
    "ops.starting": "Starting: {name}...",
    "ops.doneSnack": "{name} completed",
    "ops.warning": "Warning",
    "ops.errorSnack": "Error in {name}: {message}",
    "ops.full.title": "Full upload and cleanup",
    "ops.full.description": "Full sync: upload, update and delete orphaned documents",
    "ops.full.confirm": "New files will be uploaded, existing ones updated and orphaned documents deleted from the workspaces. Continue?",
    "ops.simulate.title": "Simulate cleanup",
    "ops.simulate.description": "See what the full upload would delete and upload, without changing anything",
    "ops.sort.title": "Update workspaces",
    "ops.sort.description": "Generate image descriptions with AI and upload files to the workspaces",
    "ops.sort.confirm": "Files will be uploaded to the workspaces and image descriptions generated with AI. Continue?",
    "ops.clean.title": "Clean folders",
    "ops.clean.description": "Delete empty workspaces from InfoHub",
    "ops.clean.confirm": "Empty workspaces will be deleted. Continue?",
    "ops.scan.title": "Scan files",
    "ops.scan.description": "Preview the folders' content without uploading anything",
    "ops.images.title": "Image descriptions",
    "ops.images.description": "Generate AI descriptions for images that have none",
    "ops.images.confirm": "AI descriptions will be generated for every image without one. Continue?",
    "ops.demoSync.title": "Sync",
    "ops.demoSync.confirm": "New files in your subfolders will be uploaded and the ones you deleted will be removed from InfoHub. Continue?",
    "ops.demoSimulate.title": "Simulate sync",
    "confirm.title": "Confirm operation",
    "confirm.body": "Are you sure you want to run this operation?",
    "progress.title": "Processing...",
    "progress.body": "Running the operation, please wait...",
    "logs.title": "Operations log",
    "logs.clear": "Clear",
    "logs.started": "System started",
    "logs.connected": "Connected to: {url} (features: {features})",
    "logs.noFeatures": "none",
    "scan.title": "Workspaces found",
    "scan.none": "No workspaces found",
    "scan.more": "+{count} more",
    "scan.noFiles": "No files",
    "simulation.titleClean": "Cleanup simulation",
    "simulation.titleSync": "Sync simulation",
    "simulation.none": "{title}: none",
    "simulation.count": "{title} ({count})",
    "simulation.more": "+{count} more (full list in the log)",
    "simulation.wouldCreate": " · would be created",
    "simulation.blocked": "⚠ Deletion blocked: {reason}",
    "simulation.notDeleted": "Will not be deleted (blocked)",
    "simulation.wouldDelete": "Would be deleted",
    "simulation.wouldUpload": "Would be uploaded",
    "simulation.noQuota": "Over the quota",
    "config.title": "Settings",
    "config.saved": "Settings saved",
    "config.savedLog": "Settings updated and saved",
    "config.saveFailed": "Could not save the settings",
    "config.field.app_title": "App title",
    "config.field.app_port": "Port",
    "config.field.anythingllm_api_key": "InfoHub API key",
    "config.field.anythingllm_base_url": "InfoHub URL",
    "config.field.ollama_base_url": "Ollama URL",
    "config.field.ollama_model": "Ollama model",
    "config.field.image_description_active": "Image descriptions",
    "config.field.watched_folders_root": "Watched root folder",
    "config.field.protected_workspaces": "Protected workspaces (comma-separated)",
    "config.field.log_level": "Log level",
    "config.field.log_file": "Log file",
    "demo.title": "Your {company} demo",
    "demo.expiresToday": "Expires today",
    "demo.oneDayLeft": "1 day left",
    "demo.daysLeft": "{days} days left",
    "demo.quota": "{days} · Documents: {used} of {max} · Space: {usedSpace} of {maxSpace}",
    "demo.docsInInfohub.one": "1 document in InfoHub",
    "demo.docsInInfohub.other": "{count} documents in InfoHub",
    "demo.steps": "1. Choose a folder on your computer: a subfolder is created for each workspace. "
                  "2. Copy each document into its subfolder. "
                  "3. Sync. To remove a document, delete it from the folder and sync again.",
    "demo.folder": "Demo folder",
    "demo.folderHint": "Choose a folder or type its path",
    "demo.chooseFolder": "Choose folder",
    "demo.chooseFolderTitle": "Choose the folder for your demo",
    "demo.sync": "Sync",
    "demo.simulate": "Simulate",
    "demo.folderFailed": "That folder could not be used: {error}",
    "demo.folderLog": "Demo folder: {path}. Subfolders: {folders}",
    "demo.folderReady": "Done: copy your documents into the subfolders and sync",
    "demo.noPicker": "If the picker did not open, type the folder path and press Enter",
    "demo.modeLog": "Demo mode: {count} workspaces from {company}",
    "demo.desktopOnly": "Demos are loaded with the desktop File Manager, which works with the folders "
                        "on your computer. Download it from “My demo” in InfoHub Chat.",
    "demo.readFailed": "Your demo could not be read from InfoHub.",
    "demo.chooseFirst": "Choose the demo folder first.",
    "demo.timeout": "InfoHub took too long. Sync again in a few minutes to check.",
    "demo.status": "InfoHub answered {status}",
    "demo.simulation": "Simulation, nothing changed: {deleted} documents would be removed and {uploaded} files uploaded.",
    "demo.simulationNoQuota": " {count} do not fit in the demo quota.",
    "demo.syncResult": "{uploaded} uploaded, {deleted} removed",
    "demo.syncNoQuota": ", {count} over the quota ({names})",
    "demo.syncErrors": ", {count} with errors: {errors}",
    "result.noWorkspaces": "The user's workspaces could not be retrieved",
    "result.connection": "Could not connect to InfoHub: {error}",
    "result.rootNotConfigured": "The watched root folder is not configured (WATCHED_FOLDERS_ROOT)",
    "result.rootMissing": "The root folder does not exist: {path}",
    "result.sorted": "Files: {uploaded} uploaded, {skipped} skipped. Images: {described} described, {existing} already had a description.",
    "result.protected": " Protected, left untouched: {names}.",
    "result.emptyCleaned": "Empty folders cleaned",
    "result.simulation": "Simulation, nothing changed: {deleted} orphaned documents would be deleted "
                         "in {workspaces} workspaces and {uploaded} files uploaded ({checked} workspaces checked).",
    "result.blocked": " Deletion blocked for safety in {count} workspaces: {names}.",
    "result.full": "{processed} workspaces processed, {uploaded} uploaded, {skipped} skipped, {deleted} deleted",
    "result.fullDeleteErrors": ", {count} deletion errors",
    "result.fullProtected": ". Protected, left untouched: {names}",
    "result.fullBlocked": ". Deletion blocked for safety in {count} workspaces: {details}",
    "result.deleteUnconfirmed": "Could not confirm that {name} was deleted",
    "result.imagesDisabled": "Image descriptions are disabled in the settings",
    "result.imagesAllDone": "All {count} images already have a description",
    "result.imagesDone": "{processed} descriptions created, {skipped} skipped",
    "result.imagesErrors": "{processed} descriptions created, {skipped} skipped, {errors} errors",
    "guard.unmounted": "the folder is in montajes_requeridos and is not mounted",
    "guard.emptyFolder": "the local folder is empty and {orphans} documents would be deleted (mount down or disk disconnected?)",
    "guard.threshold": "{orphans} of {remote} documents would be deleted ({pct} %), above the {limit} % threshold",
    "guard.noRoot": "the root folder {root} does not exist",
    "guard.rootInaccessible": "the root folder {root} is not accessible ({error})",
}

MESSAGES = {"es": ES, "en": EN}


def normalize(lang) -> str | None:
    """El idioma si es uno de los soportados; None si no."""
    return lang if isinstance(lang, str) and lang in SUPPORTED else None


class Translator:
    """Textos de una sesión: `tr("clave", campo=valor)`."""

    def __init__(self, lang: str | None = None):
        self.lang = normalize(lang) or DEFAULT

    def __call__(self, key: str, **fields) -> str:
        text = MESSAGES[self.lang].get(key) or ES.get(key) or key
        return text.format(**fields) if fields else text

    def plural(self, key: str, count: int, **fields) -> str:
        """`key.one` para 1, `key.other` para el resto."""
        return self(f"{key}.{'one' if count == 1 else 'other'}", count=count, **fields)

    def size(self, size: int) -> str:
        """Tamaño legible: en KB por debajo de 1 MB, para que no se lea «0,0 MB»."""
        if 0 < size < 1024 * 1024:
            return f"{max(1, round(size / 1024))} KB"
        text = f"{size / (1024 * 1024):.1f} MB"
        return text.replace(".", ",") if self.lang == "es" else text

    def number(self, value: float) -> str:
        """Número con el separador decimal del idioma (sin decimales sobrantes)."""
        text = f"{value:g}"
        return text.replace(".", ",") if self.lang == "es" else text


def fetch_instance_language(base_url: str, timeout: float = 5) -> str | None:
    """Idioma de la instancia de InfoHub (endpoint público), o None si no responde."""
    if not base_url:
        return None
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/api/system/instance-language",
            headers={"accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        return normalize((resp.json() or {}).get("language"))
    except Exception:
        return None


def resolve(user: str | None, instance: str | None) -> str:
    """Usuario > instancia > español."""
    return normalize(user) or normalize(instance) or DEFAULT
