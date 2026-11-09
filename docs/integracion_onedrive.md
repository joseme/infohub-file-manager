# Plan de Integración OneDrive

1. Análisis de la arquitectura actual
   - El File Manager escanea carpetas locales vía `pathlib.Path.rglob()`
   - Guarda estado de sincronización en `logs/estado_sync.json` (sha256 por archivo)
   - La subida usa multipart/form-data a `POST /api/v1/document/upload/{slug}`

2. OneDrive vía Microsoft Graph API
   - Disponible en dos modalidades:
     - Personal (cuentas @outlook, @hotmail): requiere permisos delegados + refresh token
     - Empresarial/Educativo (Microsoft 365): puede usar app-only con client credentials
   - Endpoints relevantes:
     - `GET /me/drive/root/children` (listar raíz, personal)
     - `GET /drives/{drive-id}/items/{item-id}/children` (listar carpeta, empresarial)
     - `GET /drives/{drive-id}/items/{item-id}/content` (descargar archivo)

3. Esquema de sincronización con estado
   - El estado actual guarda: `{ruta: sha256}`
   - Para OneDrive se propone: `{onedrive_id: {sha256, lastModified}}`
   - Se añade prefijo «OD:» en `estado_sync.json` para distinguir fuentes

4. Módulo a crear: `onedrive_adapter.py`
   - Clase `OneDriveAdapter` que implementa:
     - `authenticate()` -> obtiene/renueva token
     - `list_folder(folder_id)` -> generador de (id, nombre, url, modificado, sha256)
     - `download_to_temp(file_id)` -> Path temporal
     - `get_folder_id_by_path(path)` -> resuelve subcarpeta

5. Cambios en ConfigManager y UI
   - Nuevos campos en `FIELDS_SCHEMA`:
     - `onedrive_enabled` (bool)
     - `onedrive_mode` («personal» o «business»)
     - `onedrive_client_id`, `onedrive_client_secret`, `onedrive_tenant_id`
     - `onedrive_folder_path` («Documentos/General»)
   - Añadir credenciales a `.env.example`

6. Integración en el flujo de sincronización
   - Modificar `scan_files()` para iterar también sobre OneDrive si está habilitado
   - El resultado se mezcla con los archivos locales antes de llamar a `upload_file_to_workspace()`
   - Las subcarpetas de OneDrive se mapean a workspaces igual que las carpetas locales

7. Diferencias clave vs SharePoint
   - OneDrive personal no soporta app-only; requiere flujo de autorización web primero
   - Los IDs de OneDrive son GUIDs, no rutas; el estado se debe indexar por ID, no por nombre