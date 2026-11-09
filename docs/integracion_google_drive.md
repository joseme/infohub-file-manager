# Plan de Integración Google Drive

1. Resumen comparativo vs OneDrive / SharePoint

| Aspecto | Google Drive | OneDrive Personal | SharePoint / OneDrive Empresarial |
| :--- | :--- | :--- | :--- |
| Autenticacion servicio | Service Account (JSON key) | No disponible | App-only (Client Credentials) |
| Autenticacion usuario | OAuth 2.0 (3 flujos) | OAuth 2.0 obligatorio | OAuth delegado |
| Descubrimiento de cambios | `changes.list()` + watch | delta link | delta link |
| Versionado nativo | `versionHistory`, `md5Checksum` | version | version |

2. Configuracion requerida en Google Cloud Console

Opcion A - Service Account (recomendado):
- Crear proyecto en Google Cloud Console.
- Habilitar API: Google Drive API.
- Crear cuenta de servicio y generar clave JSON.
- Compartir carpetas de Drive con el email de la cuenta de servicio.

Opcion B - OAuth 2.0:
- Crear OAuth 2.0 Client ID (Desktop app).
- Descargar `credentials.json`.
- Ejecutar flujo de autorizacion local (se guarda `token.pickle`).

3. Esquema de estado en `logs/estado_sync.json`

Se propone usar el `fileId` de Google Drive con prefijo «GD:»:
```json
{
  "GD:1aBcD2EfGhIjKlMnOpQr3sTuV": {
    "source": "google_drive",
    "name": "documento.pdf",
    "md5Checksum": "d41d8cd98f00b204e9800998ecf8427e"
  }
}
```

4. Módulo a crear: `google_drive_adapter.py`

Clase `GoogleDriveAdapter` con metodos para:
- `authenticate()`
- `list_folder(folder_id, recursive=True)`
- `download_to_temp(file_id)`
- `resolve_folder_path(path_string)`

5. Deteccion de cambios

Se recomienda el uso de `changes.list()` (polling) guardando el `startPageToken` de la primera corrida para obtener solo los cambios subsiguientes.

6. Cambios en `config_manager.py` y UI

Nuevos campos:
- `google_drive_enabled` (bool)
- `google_drive_auth_mode` («service_account» o «oauth_desktop»)
- `google_drive_credentials_path` (text)
- `google_drive_folder_id` (text)