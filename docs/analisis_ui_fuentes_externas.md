# Análisis: incorporación de fuentes externas a la UI de InfoHub File Manager

Documento de análisis para modificar la interfaz de usuario e incorporar las
opciones estudiadas en `docs/`: SharePoint, OneDrive, Google Drive, SMB,
correo electrónico y Zoho. Solo cubre la UI; los adaptadores y la lógica de
sincronización se describen en los documentos de cada fuente.

## 1. Cómo está construida la UI hoy

- **Flet web (0.85.2)**, página única (`app.py`, `_main`): AppBar con botón ⚙
  (`open_config_editor`) → un único `AlertDialog` modal "Configuración".
- El diálogo se genera **desde `FIELDS_SCHEMA`** en `config_manager.py`: ~11
  campos planos, renderizados en un bucle (`build_config_editor` en `app.py`)
  con soporte para `text | number | bool | select | password`. Alto fijo 450,
  ancho 520.
- `save_config()` recorre el mismo schema, hace `config.set(key, ...)` y
  guarda `config.json`. No hay secciones, validación por campo, botones de
  "probar conexión" ni tablas.
- Fuera del diálogo: grid de tarjetas de operaciones, panel de logs, stats.
  Las fuentes externas no requieren tarjetas nuevas; los docs piden la UI en el
  panel de configuración.

## 2. Qué exige cada doc (impacto en UI)

| Doc | Campos nuevos (aprox.) | Extras de UI que el doc pide explícitamente |
|---|---|---|
| `integracion_sharepoint.txt` | `sharepoint_enabled`, `tenant_id`, `client_id`, `client_secret`, `site_url`, `folder_path` (6) | "Añadir los nuevos campos al esquema … y a la UI de Flet en `app.py`" |
| `integracion_onedrive.md` | `onedrive_enabled`, `onedrive_mode` (personal/business), `client_id`/`secret`/`tenant_id`, `folder_path` (6) | `mode` con campos condicionales; personal requiere flujo OAuth web previo |
| `integracion_google_drive.md` | `google_drive_enabled`, `auth_mode` (service_account/oauth_desktop), `credentials_path`, `folder_id` (4) | selector de auth_mode con campos condicionales |
| `integracion_smb.md` | Fase 1 (montaje ro): **ninguno**. Fase 2: `smb_enabled`, `server`, `share`, `base_path`, `username`, `password`, `domain`, `encrypt`, `max_file_size_mb` (9) | Recomendación del doc: Fase 1 = cero cambios de código/UI |
| `integracion_correo_electronico.md` | `email_source_enabled`, `email_backend` (imap/graph/gmail), `server`, `port`, `username`, `password`, `client_id`, `secret`, `tenant_id`, `folder`, `since_days`, `mark_processed`, `max_attachment_size_mb`, `allowed_extensions` (14) | §10: **sección propia «Correo Electrónico»**, botón **«Probar conexión»** (lista últimas 5 cabeceras), **tabla de reglas** remitente/asunto → workspace, **indicador de última sincronización** |
| `integracion_zoho.md` | `zoho_enabled`, `zoho_product` (desk/crm/workdrive), `zoho_dc`, `client_id`, `secret`, `refresh_token`, `org_id`, `department_id`, `module`, `workdrive_team_id`, `workdrive_workspace_id`, `since_days`, `max_file_size_mb`, `allowed_extensions` (14) | `product` con campos condicionales (org_id solo Desk, module solo CRM, team/workspace solo WorkDrive); validar `zoho_dc` |

**Total: ~50 campos nuevos si se meten a pelo en `FIELDS_SCHEMA`.** Una lista
plana de 60 filas en un diálogo de 450 px no es usable: hace falta reestructurar
el editor de configuración.

## 3. Cambios propuestos

### 3.1 Núcleo común (prerequisito)

1. **Extender `FIELDS_SCHEMA`** con dos claves opcionales, manteniendo el bucle
   de `build_config_editor`/`save_config` casi intacto:
   - `"section": "sharepoint" | "onedrive" | ...` → agrupa campos.
   - `"visible_if": ("zoho_product", "desk")` (o similar) → oculta/muestra campos
     condicionales.
2. **Nuevo tipo `"path"`** para `google_drive_credentials_path` (textfield +
   botón de file picker; Flet 0.85.2 tiene `ft.FilePicker`) y **`"list"`**
   resuelto como textfield separado por comas (`allowed_extensions`) — evitar
   inventar widgets.
3. **Reestructurar `build_config_editor`** en secciones colapsables
   (`ft.ExpansionTile` o `ft.Tabs`; en 0.85.2 existen, pero conviene verificar
   firmas exactas al implementar — hoy no se usa ninguno en el código).
   Propuesta mínima:
   - Encabezado del diálogo: "Configuración" (igual).
   - Sección **General**: los 11 campos actuales.
   - Una sección **«Fuentes de datos»** con un `ExpansionTile` por fuente:
     *SharePoint · OneDrive · Google Drive · SMB · Correo · Zoho*. Cada tile:
     - switch de habilitado (`*_enabled`) siempre visible,
     - campos de la fuente (deshabilitados si el switch está off, o simplemente
       ocultos si se prefiere simplicidad),
     - botón **«Probar conexión»** + línea de estado
       (`✓ Conectado · última sync: …` / `✗ error: …`).
   - `save_config()` sigue recorriendo el mismo schema → sin bifurcar la lógica
     de guardado.
4. **Diálogo más grande**: subir `height` del contenido de 450 → ~600 y el
   ancho 520 → ~560; sigue con scroll.
5. **Secretos**: `client_secret`/`password`/`refresh_token` como `password` con
   `can_reveal_password` (patrón existente), y dejar en el label/hint que se
   prefiere variable de entorno (`SMB_PASSWORD`, `ZOHO_*`, etc., como piden los
   docs). Nunca loguearlos (el `add_log` actual no vuelca valores de config —
   mantenerlo así).

### 3.2 Por fuente (solo lo específico)

- **SharePoint**: tile con los 6 campos + «Probar conexión» (token OAuth2 +
  listado del `folder_path`). Validación de `site_url` con `urlparse` antes de
  guardar.
- **OneDrive**: `onedrive_mode` como `select`. Si `personal` → mostrar aviso +
  campos de refresh token (no app-only posible); si `business` → `tenant_id` +
  client credentials (mismo patrón que SharePoint).
- **Google Drive**: `auth_mode` como `select`. `service_account` →
  `credentials_path` (file picker) + `folder_id`; `oauth_desktop` → texto
  explicativo + mismo `folder_id` (el `token.pickle` se genera fuera de la
  app).
- **SMB**: **Fase 1 (recomendada por el doc): cero UI** — solo documentar
  montaje en `docs/` y añadir el guarda anti-falso-vacío en `sync_bot.py`
  (fuera de alcance UI). Fase 2 (solo si hace falta): tile con los 9 campos;
  `smb_password` como password + hint de variable de entorno.
- **Correo**: la sección más grande; cumple §10 literal:
  - `backend` como `select` (imap/graph/gmail); `server`/`port` solo visibles
    si `imap`; `client_id`/`secret`/`tenant_id` solo si `graph`/`gmail`.
  - «Probar conexión» → lista las últimas 5 cabeceras en un diálogo/snackbar
    (sin descargar adjuntos).
  - **Tabla de reglas de clasificación** remitente|asunto|carpeta → workspace:
    `DataTable` pequeña con añadir/eliminar fila; se persiste como lista en
    `config.json` (`email_rules: [{match, type, workspace}]`) — es el único
    campo que no cabe en el patrón textfield.
  - Indicador «Última sincronización de correo: …» (leer de
    `logs/estado_sync.json` o de un nuevo `logs/estado_fuentes.json`).
- **Zoho**: `product` como `select` con **campos condicionales** vía
  `visible_if`: `org_id`/`department_id` (desk), `module` (crm),
  `workdrive_team_id`/`workdrive_workspace_id` (workdrive); `zoho_dc` como
  `select` (`com|eu|in|com.cn|com.au`). «Probar conexión» = refresh del token +
  llamada barata al endpoint del producto.

### 3.3 Fuera del diálogo de configuración

- Los docs no piden tocar el grid de operaciones: `scan_files` concatenará
  fuentes y la lógica de `upload_file_to_workspace` se reutiliza. Como mucho,
  el botón «Escanear Archivos» mostrará en el resultado cuántas provienen de
  fuentes externas (ya hay UI para mostrar resultados por workspace en
  `show_workspaces`).
- Modo demo (`demo_state`): sin cambios; configuración y tour siguen ocultos
  ahí.

## 4. Orden de implementación sugerido (UI solamente)

1. **Paso 0 (común)**: `section`/`visible_if` en el schema + secciones
   colapsables en el diálogo + «Probar conexión» genérico (botón + estado).
   Sin esto, todo lo demás se degrada en una lista ilegible.
2. **SMB Fase 1**: nada de UI; documentación + guarda anti-falso-vacío
   (código, no UI).
3. **SharePoint y OneDrive business** (mismo patrón OAuth2 app-only) → un solo
   tile/plantilla.
4. **Google Drive** (service account) → reutiliza file picker + test.
5. **Correo** → el más costoso (tabla de reglas, test que lista cabeceras,
   indicador).
6. **Zoho** → campos condicionales + test por producto; **OneDrive personal**,
   **email IMAP/OAuth** y **SMB Fase 2** solo si el caso de negocio los exige.

## 5. Riesgos / notas

- **Volumen**: ~50 campos nuevos; sin secciones el diálogo es inutilizable — el
  Paso 0 es obligatorio, no opcional.
- **Secretos en `config.json`**: los docs insisten en variables de entorno/
  keyring; la UI debe al menos advertirlo en hints y enmascarar. Ideal: types
  `password` + no persistir si el campo queda vacío y existe la env var
  (patrón ya usado para `ANYTHINGLLM_API_KEY`).
- **Condicionalidad dinámica**: cambiar un `select` (`zoho_product`,
  `email_backend`, `onedrive_mode`, `auth_mode`) debe reconstruir/ocultar
  campos sin perder lo tecleado → rebuild parcial del `Column`, no
  `page.update()` global a ciegas.
- **Validación en guardado**: obligatorio validar `zoho_dc`, `email_port`
  numérico, extensiones con punto, URLs con `urlparse`; hoy `save_config` no
  valida nada (solo `int()` para `number`).
- **Flet 0.85.2**: `ExpansionTile`/`Tabs` no se usan hoy en el código —
  verificar sus firmas al implementar (la versión es reciente y el API de Flet
  cambia entre menores).
- **«Probar conexión» en hilo**: las llamadas de red deben ir en
  `threading.Thread` como las operaciones existentes (`wrap_operation`), nunca
  en el hilo de UI.
- **Estado de sincronización**: los docs proponen prefijos en `estado_sync.json`
  (`OD:`, `GD:`, `SMB:`, `EMAIL:`, `ZOHO:`); el indicador de última sync
  necesita que el backend escriba esa fecha — la UI solo la lee.

## 6. Pendientes / no verificado

- No existe aún ningún adaptador (`adapters/`, `email_adapter.py`, etc.) en el
  repo — todo esto es UI para funcionalidad que los docs solo planifican; los
  «Probar conexión» dependen de que esos módulos existan o se stubbeen.
- No se ha revisado el tour (`assets/tour/tour.js`), que podría querer un paso
  nuevo para «Fuentes» — detalle menor a decidir al implementar.
- No se ha verificado el API exacto de `ExpansionTile`/`Tabs`/`FilePicker` en
  flet 0.85.2.
