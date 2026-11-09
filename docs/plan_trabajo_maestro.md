# Plan de trabajo maestro — Fuentes externas + Programación periódica

InfoHub File Manager · consolidado a partir de los 9 documentos de `docs/`
(2026-11-08). Sustituye el cronograma de `plan_trabajo_fuentes_cloud.md`, que
quedó desfasado al añadirse correo, Zoho y SMB, y fija un orden único entre
ese plan, `analisis_ui_fuentes_externas.md` y `plan_opcion_a_programacion.md`.

---

## 0. Diagnóstico de los documentos

### 0.1 Qué hay

| Documento | Tipo | Madurez |
|---|---|---|
| `integracion_sharepoint.txt` | Diseño de fuente | Media (sin errores ni pruebas) |
| `integracion_onedrive.md` | Diseño de fuente | Media |
| `integracion_google_drive.md` | Diseño de fuente | Baja (escueto: sin errores, pruebas ni tipos especiales; estos están en el plan cloud) |
| `integracion_smb.md` | Análisis + recomendación | Alta |
| `integracion_correo_electronico.md` | Análisis técnico | Alta |
| `integracion_zoho.md` | Análisis técnico | Alta |
| `analisis_ui_fuentes_externas.md` | Impacto en UI | Alta (verificado contra el código) |
| `plan_opcion_a_programacion.md` | Plan ejecutable | Alta (fases, tests, criterios) |
| `plan_trabajo_fuentes_cloud.md` | Plan general | Desfasado (ver 0.2) |

### 0.2 Inconsistencias y huecos detectados

1. **Huérfanos frente a fuentes externas (CRÍTICO, verificado en el código).**
   `sync_bot.py:313-315` define como huérfano todo documento del workspace sin
   equivalente **local**. La corrida programada del domingo 07:30
   (`--borrar-huerfanos`) borraría todo lo subido desde SharePoint, correo,
   Zoho, etc. Ningún documento lo menciona. Hay que resolverlo **antes** de que
   la primera fuente externa suba nada.
2. **El formato de estado no coincide con el real.** Los documentos proponen
   claves planas con prefijo (`OD:…`, `GD:…`, `EMAIL:…`) en `estado_sync.json`,
   pero el estado real es `estado[slug][nombre_remoto] = {sha, size, intentos}`
   (`sync_bot.py:302-306`). Hay que decidir el esquema (propuesta en F3.3).
3. **SharePoint: ¿`id` o `eTag`?** El documento de SharePoint usa `id` como
   clave; el plan cloud (T2.3) usa `eTag` como "identificador único". El `eTag`
   cambia con cada versión, así que **la clave debe ser `id`** y
   `eTag`/`cTag`/`quickXorHash` sirven para detectar cambios.
4. **«Selector de fuente en UI» (plan cloud T5.1) frente al análisis de UI**,
   que dice que las fuentes van en ⚙ Configuración y no requieren tarjetas
   nuevas. Se adopta el análisis de UI: las fuentes se activan por
   configuración y el flag `--fuente` queda solo para la CLI de `sync_bot`.
5. **El cronograma del plan cloud** solo cubre SharePoint, OneDrive y Drive;
   correo, Zoho y SMB aparecen como «semana 1.5/1.6/1.7» sin hueco real.
6. **`plan_opcion_a_programacion.md`** es independiente de las fuentes y aporta
   valor inmediato; no está en ningún cronograma.
7. **Ningún documento** contempla el empaquetado: las dependencias nuevas
   (msal, google-api-python-client…) tienen que entrar en `build.spec`
   (PyInstaller) y en el `Dockerfile`.
8. **`crontab.txt` contiene entradas de otros proyectos** (cr-tributario,
   cr-laboral, cr-seguros). Esto confirma que `instalar_cron.sh` debe fusionar
   usando un marcador y nunca sobrescribir el crontab.
9. **Dependencia SDK:** el plan cloud pide `msgraph-sdk-python`. Se recomienda
   `msal` + `requests` (ya presente): es mucho más ligero, más fácil de
   congelar con PyInstaller y suficiente para listar y descargar.

### 0.3 Estado del código (punto de partida verificado)

- No existen `adapters/`, `email_adapter.py` ni ningún otro adaptador.
- `FIELDS_SCHEMA` tiene 11 campos planos (`config_manager.py:32-44`).
- `requirements.txt`: flet 0.85.2, python-dotenv, requests, pytest.
- `sync_bot.py` (482 líneas) tiene `main()` monolítico; no escribe
  `ultima_sync.json`; no tiene guarda anti-falso-vacío.
- Tests: `tests/app_test.py`, `config_manager_test.py` y otros; `pytest.ini`.

---

## 1. Decisiones a cerrar antes de empezar (F0)

| # | Decisión | Recomendación |
|---|---|---|
| D1 | ¿Qué fuentes tienen caso de negocio real **ya**? | ✅ **Decidido (2026-11-08): hay clientes para SharePoint y Zoho Desk.** Alcance comprometido: F1, F2, F3, F4 (solo SharePoint) y F7. OneDrive, Google Drive y Correo pasan a la cartera sin cliente (F8) |
| D2 | Esquema de estado para fuentes externas | Archivo aparte `logs/estado_fuentes.json` (ver F3.3) |
| D3 | ¿Las fuentes externas borran en InfoHub cuando el origen elimina? | **No en v1.** Solo altas y actualizaciones; el borrado se añade más adelante con guardas |
| D4 | Secretos | Variable de entorno > `config.json`; `keyring` opcional en F9 |
| D5 | Estado programado: ¿dashboard o diálogo? | Dashboard (recomendado en el plan Opción A) |
| D6 | «Ejecutar ahora» en frozen | (b) `run()` importable desde `sync_bot` |
| D7 | Cron en Docker | Documentar el cron del host; supercronic solo si se pide |
| D8 | Accesos de los clientes | Pedirlos en F0: son la ruta crítica de F4 y F7. Lista concreta en §1.1 |

### 1.1 Qué hay que pedir a cada cliente (enviar en la semana 1)

**Cliente SharePoint** (lo hace el administrador del tenant M365):
- Registrar una aplicación en Entra ID y entregar el **Tenant ID**, el
  **Client ID** y un **Client Secret** (anotar su caducidad: 6, 12 o 24
  meses).
- Permisos de aplicación. Recomendado: **`Sites.Selected`** con concesión
  solo al sitio en cuestión (mínimo privilegio y más fácil de aprobar por TI).
  Alternativa: `Sites.Read.All` + `Files.Read.All`, como dice el documento,
  pero dan lectura a **todo** el tenant.
- **Admin consent** concedido.
- URL del sitio y ruta de la carpeta raíz, y qué subcarpetas van a qué
  workspace.
- Una carpeta de prueba con 5–10 documentos representativos (tildes, PDF
  grande, Office).
- Confirmar dónde corre el File Manager para ese cliente (VPS o equipo
  propio): SharePoint es nube, así que no hay problema de red, pero cambia el
  despliegue del cron y de los secretos.

**Cliente Zoho Desk** (lo hace un administrador de Zoho Desk):
- **Data center** de la cuenta (`.com`, `.eu`, `.in`…). Se ve en la URL de
  Desk.
- **Self Client** en <https://api-console.zoho.com/> (el del DC
  correspondiente): **Client ID** y **Client Secret**, y un *grant code* con
  los scopes `Desk.tickets.READ,Desk.basic.READ` (este último para leer
  departamentos). Con el grant code generamos el **refresh token**; el code
  caduca en minutos, así que conviene hacerlo en una llamada conjunta.
- **orgId** (Desk → Configuración → Developer Space → API).
- Departamentos y etiquetas que existen, y la tabla deseada de **departamento
  o etiqueta → workspace**.
- Si quieren también los adjuntos de **comentarios** del ticket o solo los
  del ticket (§11 del documento de Zoho).
- Antigüedad de la primera carga (`since_days`): ¿todo el histórico o los
  últimos N días?
- ¿Es el mismo flujo que hoy alimenta `zoho-tickets`? Si es así, aplica el
  plan de transición F7.4.

**Entregable F0:** este documento con las decisiones marcadas, más las
correcciones 0.2.3 y 0.2.4 aplicadas en los documentos originales.
**Esfuerzo:** 0,5 d.

---

## 2. Fases

Estimaciones en días-persona de desarrollo efectivo. Ruta crítica:
F1 → F3 → F4 (SharePoint) → F7 (Zoho Desk). F2 es paralelizable con todo lo
demás. **F5 y F6 quedan en espera hasta que haya cliente**; su diseño se
mantiene abajo para no perderlo.

```
F0 Decisiones ─┬─ F1 Seguridad borrado + SMB F1 ─┬─ F3 Núcleo adaptadores + UI paso 0 ─┬─ F4 SharePoint ──┐
               │                                  │                                       └─ F7 Zoho Desk ───┴─ F9 Release + piloto
               └─ F2 Programación (Opción A) ─────┘
                                     (en espera, sin cliente: F5 Google Drive · F6 Correo · F8 opcionales)
```

F4 y F7 son independientes entre sí (las dos solo dependen de F3). Si los
accesos de un cliente llegan antes que los del otro, se empieza por esa fuente.

### F1 — Seguridad de borrado + SMB Fase 1 (1,5 d) · PRIORIDAD MÁXIMA

Objetivo: que ninguna caída de origen ni fuente nueva pueda vaciar un
workspace.

| Tarea | Detalle | Archivos |
|---|---|---|
| 1.1 Guarda anti-falso-vacío ✅ | **Implementado (rama `feature/guardas-borrado`).** Raíz listable (`raiz_accesible`); carpetas en `montajes_requeridos` deben estar montadas (`os.path.ismount`); se bloquea **solo el borrado** si la carpeta está vacía o si se iría más de `umbral_borrado_pct` (50) % del workspace con más de `minimo_borrado` (10) documentos. *Cambio respecto del diseño:* la base de comparación es el número de documentos del servidor, no el conteo de la corrida anterior, porque `estado_sync.json` nunca elimina entradas y ese conteo crece sin límite. Así no se necesita estado y la regla funciona igual en el panel. `--forzar-borrado` salta las guardas de vacío y umbral, pero no la de montaje. Aviso `⚠ BORRADO BLOQUEADO` en el resumen y en Telegram | `sync_guards.py`, `sync_bot.py`, `sync_bot.json` |
| 1.2 La misma guarda en la UI ✅ | El borrado de huérfanos desde la UI (`app.py`) usa la misma función compartida | `app.py` (extraer helper a un módulo común, p. ej. `sync_guards.py`) |
| 1.3 Huérfanos conscientes de la fuente ✅ | Excluir del cálculo de huérfanos los nombres remotos registrados por fuentes externas (en `estado_fuentes.json`, vacío por ahora). Así se deja preparado el punto de extensión para F3 | `sync_bot.py:313` y el equivalente en `app.py` |
| 1.4 Guía de montaje SMB ✅ (`docs/guia_montaje_smb.md`) | `docs/guia_montaje_smb.md`: fstab `ro,_netdev,nofail,vers=3.0`, archivo de credenciales 600, Windows `net use`/UNC, puerto 445 y VPN (nota del VPS) | docs |
| 1.5 Tests ✅ (34 tests en `tests/sync_guards_test.py`) | Raíz inexistente → no borra; caída del 100 % y del 60 % → no borra; caída por debajo del umbral → borra; nombre registrado por una fuente externa → no es huérfano | `tests/sync_guards_test.py` |

**Aceptación:** al desmontar la carpeta a mitad de corrida no se borra nada en
InfoHub (prueba manual con un montaje o bind mount); `pytest` en verde.

### F2 — Programación periódica, Opción A (5–7 h) · paralelizable

Se ejecuta tal cual `plan_opcion_a_programacion.md`, con este ajuste de orden:

| Tarea | Detalle | Estimación |
|---|---|---|
| 2.1 `ultima_sync.json` | `json.dump` atómico (tmp + `os.replace`) de los resultados al final de `main()`. Incluir también `guarda_activada` de F1 | 1 h |
| 2.2 Helper `format_ultima_sync(dict) -> str` | Puro y testeable sin Flet | 0,5 h |
| 2.3 Bloque «Sincronización programada» en el dashboard | Lee al arrancar y con «Actualizar Estado»; expander por carpeta; estado neutro si no hay archivo o está corrupto | 1,5 h |
| 2.4 Extraer `run(bot_cfg, args)` de `main()` | `main()` queda como envoltorio de argparse; el lock se mantiene dentro de `run` | 1 h |
| 2.5 «Ejecutar ahora» + checkbox «Simulación» | Hilo y guarda `sync_running`; mensaje «Ya hay una sincronización en curso» como snackbar; logs al panel mediante un handler de `logging` | 1,5 h |
| 2.6 `scripts/instalar_cron.sh` | Marcador `# infohub-file-manager` solo en las líneas propias; fusiona con `crontab -l`; idempotente | 1 h |
| 2.7 README + tests | `tests/test_ultima_sync.py` (válido, corrupto, inexistente, atomicidad) y el camino de guarda | 1 h |

**Aceptación:** criterios 1–5 de `plan_opcion_a_programacion.md` §8.

### F3 — Núcleo de adaptadores + UI «paso 0» (4–5 d)

Es el prerrequisito de toda fuente externa. Sin esta fase, cada fuente
reinventaría la integración.

**3.1 Interfaz común — `adapters/base.py`**

```python
@dataclass
class RemoteFile:
    source: str          # "sharepoint" | "onedrive" | "gdrive" | "email" | "zoho" | "smb"
    id: str              # id estable del origen (id Graph, fileId, Message-ID+adjunto…)
    name: str
    workspace_folder: str  # carpeta lógica → workspace_map (igual que carpetas locales)
    size: int | None
    modified: datetime | None
    version_tag: str | None  # eTag/cTag/md5Checksum/sha… para detectar cambios sin descargar
    meta: dict           # remitente, asunto, ticket… (para reglas)

class AbstractSourceAdapter(ABC):
    name: str
    def authenticate(self) -> None: ...           # lanza SourceAuthError
    def test_connection(self) -> list[str]: ...  # 5 líneas legibles para la UI
    def list_files(self) -> Iterator[RemoteFile]: ...
    def download_to_temp(self, f: RemoteFile, tmpdir: Path) -> Path: ...
```

- `resolve_workspace` **no** va en el adaptador (a diferencia de la propuesta
  del plan cloud): lo resuelve el motor con `workspace_map` a partir de
  `workspace_folder` más un motor de reglas (3.4).
- `get_file_hash` desaparece: el sha256 se calcula localmente tras descargar,
  y `version_tag` evita descargas innecesarias.
- Excepciones tipadas: `SourceAuthError`, `SourceUnavailable`, `RateLimited`
  (con `retry_after`).
- Utilidades comunes en `adapters/http.py`: sesión `requests` con
  reintentos y backoff exponencial que respeta `Retry-After`, timeouts y
  enmascarado de secretos en los logs.

**3.2 Registro y motor — `adapters/__init__.py` + `sources_sync.py`**
- `enabled_adapters(config) -> list[AbstractSourceAdapter]`.
- `sync_source(adapter, mgr, estado_fuentes, dry, limite)`: lista → filtra
  (extensión, tamaño y `since_days` con valores por defecto comunes) →
  compara `version_tag` con el estado → descarga a `BASE_DIR/.temp/<uuid>` →
  sha256 → `mgr.upload_file_to_workspace(...)` → actualiza el estado → borra el
  temporal (incluso si falla, con `finally`).
- Lo invocan `sync_bot.run()` (nuevo flag `--fuente {local,todas,<nombre>}`,
  por defecto `todas`) y `scan_files()` en `app.py` (que devuelve también un
  conteo por fuente para el resultado de «Escanear Archivos»).
- Los resultados de cada fuente se agregan a `ultima_sync.json` (F2) con la
  clave `fuentes`.

**3.3 Estado — `logs/estado_fuentes.json`**

```json
{"sharepoint": {"<id>": {"version_tag": "...", "sha": "...", "slug": "odoo17",
                          "remote_name": "contrato.pdf", "intentos": 0, "ts": "..."}},
 "_meta": {"gdrive": {"start_page_token": "..."}, "onedrive": {"delta_link": "..."}}}
```
- Archivo separado: no toca el formato de `estado_sync.json`, que hoy funciona.
- `remote_name` + `slug` alimentan la exclusión de huérfanos de F1.3.
- Escritura atómica; mismo lock que `sync_bot`.
- Se documentan las equivalencias con los prefijos de los documentos (`SP:`,
  `OD:`, `GD:`, `EMAIL:`, `ZOHO:desk:`…) para que sigan siendo legibles.

**3.4 Reglas de clasificación — `adapters/rules.py`**
- Lista ordenada `[{campo, op, valor, workspace}]` donde `campo ∈ {remitente,
  asunto, carpeta, departamento, tag, modulo}` y `op ∈ {contiene, igual,
  regex}`. La primera coincidencia gana; si ninguna coincide, se usa
  `fallback_workspace` de la fuente.
- La usan Zoho (§10), que es su **primer consumidor** porque es una fuente
  comprometida, y en el futuro el correo (§4 del documento de correo). Las
  fuentes de archivos (SharePoint) usan `workspace_folder`.
- Como Zoho la necesita, el widget de **tabla de reglas** (tipo `rules`) se
  construye en F7, no en F6 como decía el análisis de UI.
- Se persiste en `config.json` como `<fuente>_rules`.

**3.5 Configuración — `config_manager.py`**
- Claves opcionales en `FIELDS_SCHEMA`: `section`, `visible_if: (key, value |
  tuple)`, `env` (nombre de la variable de entorno que tiene prioridad),
  `validate` (nombre de un validador: `url`, `port`, `ext_list`, `zoho_dc`).
- Tipos nuevos: `path` (campo de texto + `FilePicker`), `list` (CSV → lista) y
  `rules` (tabla, solo para correo y Zoho).
- `get_secret(key)`: env > config. Si el campo de la UI queda vacío y existe la
  variable de entorno, no se persiste (patrón de `ANYTHINGLLM_API_KEY`).
- Validación en `save_config()` con errores por campo; hoy no valida nada.
- `.env.example`: añadir todas las variables (`SHAREPOINT_*`, `ONEDRIVE_*`,
  `GOOGLE_*`, `EMAIL_*`, `ZOHO_*`, `SMB_*`).

**3.6 UI paso 0 — `app.py` (`build_config_editor`)**
- Primero, una spike de 2 h: verificar la API de `ExpansionTile`, `Tabs` y
  `FilePicker` en flet 0.85.2 con un script desechable.
- Diálogo de 560×600 con secciones «General» (los 11 campos actuales) y
  «Fuentes de datos», con un `ExpansionTile` por fuente registrada.
- Cada tile tiene: interruptor `*_enabled`, campos con `visible_if` (rebuild
  parcial del `Column` conservando lo tecleado), botón **«Probar conexión»**
  en un hilo y una línea de estado (`✓ Conectado · última sync: …` /
  `✗ <error sin secretos>`).
- La sección solo muestra las fuentes con adaptador implementado: la UI crece
  fase a fase sin campos huérfanos.
- Modo demo: sin cambios (⚙ sigue oculto).

**3.7 Tests**
- `FakeAdapter` en memoria → `sync_source` sube, omite si `version_tag` no
  cambió, reintenta los errores, borra los temporales y respeta `dry` y el
  límite.
- Schema: `visible_if`, validadores, prioridad de la variable de entorno y no
  persistencia de secretos.
- Reglas: orden, fallback y regex inválida (error en validación, no en
  ejecución).

**Aceptación:** con `FakeAdapter` habilitado, `sync_bot.py --dry-run` y
«Escanear Archivos» muestran sus archivos; una corrida real los sube; una
corrida posterior con `--borrar-huerfanos` **no** los borra; el diálogo muestra
la sección «Fuentes» con el tile de prueba.

### F4 — Microsoft Graph: SharePoint (3,5 d) · CLIENTE COMPROMETIDO

Se construye solo SharePoint, pero con `graph_common.py` separado: así
OneDrive Business (4.3) queda como un incremento de unos 0,5–1 d cuando haya
cliente, y el correo vía Graph (F6) también lo reutiliza.

| Tarea | Detalle |
|---|---|
| 4.1 `adapters/graph_common.py` | Token MSAL con caché en memoria y renovación; `get(path)` paginado (`@odata.nextLink`); throttling 429/503 con `Retry-After`; listado recursivo y descarga por `/content` (redirección) |
| 4.2 `adapters/sharepoint.py` | `site_url` → `GET /sites/{host}:/{path}` → drive id → item de `folder_path`. Primer nivel bajo la carpeta = `workspace_folder`. Clave = `id`; `version_tag` = `cTag` (cambia solo con el contenido) |
| 4.3 *(en espera, sin cliente)* `adapters/onedrive.py` (business) | `/users/{upn}/drive` (se añade el campo `onedrive_user` que falta en el documento: app-only no tiene `/me`) + `folder_path`. Delta link en `_meta` como mejora: v1 puede usar el listado completo con `cTag` |
| 4.4 Configuración y UI | 6 campos; `site_url` validado con `urlparse`; «Probar conexión» = token + 5 primeros elementos de la carpeta. Mensajes claros para los errores típicos de un cliente nuevo: `AADSTS7000215` (secret inválido), `AADSTS7000222` (secret caducado), 403 (falta consent o la concesión `Sites.Selected` al sitio) |
| 4.5 Tests | Respuestas Graph grabadas (fixtures JSON) con `requests` simulado: paginación, 429, token expirado, carpeta inexistente, nombres con tildes |
| 4.6 Prueba real | Primero un tenant propio de desarrollo (M365 Developer) mientras llegan los accesos; después la carpeta de prueba del cliente (§1.1) en dry-run y luego real |
| 4.7 Operación | Alerta por Telegram cuando falten 30 días para que caduque el client secret (fecha guardada como campo informativo `sharepoint_secret_expira`) |

Dependencia: `msal`. **Aceptación:** sincronizar la carpeta de prueba del
cliente a sus workspaces; al cambiar un archivo se re-sube; si no cambia, no
se descarga; `--borrar-huerfanos` no lo toca.

### F5 — Google Drive, Service Account (2,5 d) · EN ESPERA (sin cliente)

| Tarea | Detalle |
|---|---|
| 5.1 `adapters/gdrive.py` | `google-auth` + `google-api-python-client`; `files.list` con `q="'<folder>' in parents and trashed=false"`, recursivo, `supportsAllDrives=True`; `version_tag` = `md5Checksum` (o `modifiedTime` para nativos) |
| 5.2 Tipos especiales | Docs/Sheets/Slides → `files.export` a PDF (límite de 10 MB de export: registrar y omitir); shortcuts → `shortcutDetails.targetId` |
| 5.3 Cambios incrementales | v1: listado completo + `md5`. v2 (opcional): `changes.list` con `startPageToken` en `_meta` |
| 5.4 UI | `auth_mode` (`service_account` en v1; `oauth_desktop` se difiere a F8), `credentials_path` (tipo `path`), `folder_id` |
| 5.5 Tests | Fixtures: paginación `nextPageToken`, export de un Doc nativo, shortcut, papelera, 403 por carpeta no compartida con la service account (mensaje claro: «comparte la carpeta con <email SA>») |

### F6 — Correo electrónico (4–5 d) · EN ESPERA (sin cliente)

Orden interno: **Graph primero** (cubre M365 sin el problema de la
autenticación básica y reutiliza `graph_common` de F4), luego **IMAP con
contraseña de aplicación**, y Gmail API en F8.

| Tarea | Detalle |
|---|---|
| 6.1 `adapters/email/base.py` | `RemoteFile` por adjunto: `id = Message-ID + '/' + nombre normalizado`, `meta = {remitente, asunto, carpeta, fecha}`; workspace por reglas (F3.4) con fallback `Correo General` |
| 6.2 Backend Graph | `/users/{user}/mailFolders/{folder}/messages?$filter=receivedDateTime ge … and hasAttachments eq true`; solo `fileAttachment` y no `isInline`; `$value` para descargar; mover a `InfoHub/Procesados` si `mark_processed` (requiere `Mail.ReadWrite`, documentarlo) |
| 6.3 Backend IMAP | `imaplib.IMAP4_SSL` (se rechaza el texto plano); `SEARCH SINCE`; recorrido MIME recursivo; nombres RFC 2047/2231 con `email.header`/`get_filename()`; `MOVE` o `COPY`+`\Deleted` para «procesados» |
| 6.4 Filtros de seguridad | Lista negra de extensiones (`.exe .bat .js .vbs .scr .cmd .ps1`), lista blanca configurable, tamaño máximo (25 MB por defecto) comprobado **antes** de descargar con el `size` de Graph o el `BODYSTRUCTURE` de IMAP; `.p7m`/`.eml` se suben tal cual en v1 |
| 6.5 UI (§10 del documento) | Sección propia; `backend` con `visible_if`; «Probar conexión» = 5 últimas cabeceras (sin adjuntos); **tabla de reglas** (`DataTable` con añadir/quitar); «Última sincronización» leída de `estado_fuentes._meta.email.last_run` |
| 6.6 Tests | Los 7 casos de §11 del documento con `.eml` de fixture (IMAP) y JSON (Graph), más el mismo adjunto en dos correos (deduplicación por sha) |

### F7 — Zoho Desk (3,5 d) · CLIENTE COMPROMETIDO

Desk primero porque sustituye el flujo manual de `zoho-tickets`
(`sync_bot.json`).

| Tarea | Detalle |
|---|---|
| 7.1 `adapters/zoho/auth.py` | Refresh token self-client → access token; dominio por `zoho_dc` (`accounts.zoho.<dc>`, `desk.zoho.<dc>`); `zoho_dc` validado contra la lista; error claro si el DC es incorrecto (`invalid_client`/`invalid_code`) |
| 7.2 `adapters/zoho/desk.py` | Tickets con `modifiedTime` ≥ `since_days` (cabecera `orgId`); adjuntos del ticket (los de comentarios quedan para v2, decisión §11); ignorar `DOWNLOAD_NOT_ALLOWED`; `meta = {departamento, tags, asunto, remitente}` → reglas; `id = desk:{ticketId}:{attachmentId}` |
| 7.3 Rate limit | `RateLimited` + backoff (código `RATE_LIMIT_EXCEEDED` / HTTP 429) |
| 7.4 Transición | Procedimiento documentado: activar Desk en dry-run → comparar con `zoho-tickets` → desactivar esa carpeta en `sync_bot.json`. Riesgo de duplicados: mismo archivo con nombre distinto; mitigarlo comparando sha contra `estado_sync` del mismo slug |
| 7.5 UI | `product` con `visible_if` (solo `desk` habilitado en v1), `dc`, `org_id` y `department_id`. **Tabla de reglas** (tipo `rules`: `DataTable` con añadir/quitar filas, campos `departamento`/`tag`/`asunto`/`remitente`) más un `fallback_workspace`. «Probar conexión» = refresh del token + 5 últimos tickets con adjuntos (id, asunto, departamento) para que el cliente valide las reglas |
| 7.5b Precarga de reglas | Botón «Cargar departamentos» que lee `/api/v1/departments` y crea una fila por departamento para que el cliente solo asigne el workspace (+0,5 d, incluido en la estimación) |
| 7.6 Tests | Los casos de §12 del documento aplicables a Desk, con fixtures |

### F8 — Opcionales, solo con caso de negocio (estimación por pieza)

| Pieza | Esfuerzo | Disparador |
|---|---|---|
| OneDrive Business (sobre `graph_common` de F4) | 0,5–1 d | Cliente con OneDrive de M365 |
| Google Drive (F5 completo) | 2,5 d | Cliente con Drive |
| Correo (F6 completo; Graph reutiliza F4 y las reglas reutilizan F7) | 3,5–4 d | Cliente con buzón de entrada de documentos |
| Zoho CRM (adjuntos por módulo) | 2 d | Cliente con casos o reclamaciones en CRM |
| Zoho WorkDrive (recursivo) | 2 d | Cliente que usa WorkDrive como repositorio |
| OneDrive Personal (OAuth delegado + refresh token) | 2 d | Usuario individual sin M365 |
| Google Drive OAuth Desktop | 1 d | Sin posibilidad de service account |
| Gmail API | 2 d | Buzones Gmail o Workspace |
| SMB Opción B (`smbprotocol`) | 3 d | Windows/.exe sin montaje o varios NAS desde la UI |
| Delta/changes incrementales (OD/GD) | 1–2 d | Carpetas con más de 10k archivos |
| Borrado sincronizado desde el origen | 2 d | Tras decidir D3, con las guardas de F1 |
| Keyring para secretos | 1 d | Entornos multiusuario |

### F9 — Documentación, empaquetado y release (2 d, al cierre de cada fuente + final)

- **Por fuente** (se hace dentro de su fase, no al final): guía de alta del
  portal (Entra ID, Google Cloud, Zoho API Console), permisos mínimos y
  solución de problemas → `USER_GUIDE_ES.md` y `docs/guia_<fuente>.md`.
- `requirements.txt` con versiones fijadas; las dependencias pesadas como
  extras opcionales con import perezoso dentro de cada adaptador, para que una
  fuente sin la librería instalada se muestre como «no disponible» y no rompa
  el arranque.
- `build.spec`: `hiddenimports`/`collect_submodules` para msal, googleapiclient
  y google.auth; probar el `.exe` y el binario Linux con una fuente habilitada.
- `Dockerfile` / `docker-compose.yml`: dependencias y montaje de `logs/` y
  `.temp/`; documentar el cron del host (D7).
- README: sección «Fuentes externas» y release notes.

---

## 3. Cronograma propuesto (1 desarrollador)

Alcance comprometido: **SharePoint + Zoho Desk** (D1).

| Semana | Fases | Hito |
|---|---|---|
| 1 | F0, F1, F2 · **pedir los accesos de §1.1 a ambos clientes** | Borrado seguro + estado y «Ejecutar ahora» en el dashboard (entregable a producción) |
| 2 | F3 | Motor de fuentes + UI de configuración por secciones (con `FakeAdapter`) |
| 3 | F4 | SharePoint: dry-run y luego real con la carpeta de prueba del cliente |
| 4 | F7 | Zoho Desk con reglas por departamento/etiqueta; transición de `zoho-tickets` |
| 5 | F9 + piloto | Guías de SharePoint y Zoho, empaquetado, release; una semana de piloto con ambos clientes vigilando `ultima_sync.json` y Telegram |

Total comprometido: unos **16–18 días-persona** (≈ 4–5 semanas), frente a los
24–27 del alcance completo. F5, F6 y F8 se planifican cuando aparezca un
cliente. Si un cliente entrega sus accesos antes, F4 y F7 se intercambian sin
coste.

---

## 4. Riesgos principales

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Borrado masivo por huérfanos o falso vacío | Pérdida de documentos en InfoHub | F1 antes que cualquier fuente; las fuentes no borran en v1 (D3) |
| Cuentas y permisos de prueba tardan (admin consent, Google Cloud, Zoho) | Bloquea F4–F7 | Pedirlos en F0 (D8); desarrollar con fixtures mientras tanto |
| API de Flet 0.85.2 (`ExpansionTile`/`FilePicker`) distinta de la esperada | Retrasa F3.6 | Spike de 2 h al inicio de F3; plan B con `Tabs` o columnas con encabezados |
| Secretos en `config.json` | Fuga de credenciales | Variable de entorno con prioridad, campos `password`, no persistir si hay variable, logs enmascarados, test explícito |
| Empaquetado PyInstaller con las librerías de Google y MS | El `.exe` falla en campo | Imports perezosos + prueba del binario en cada fase |
| Duplicados en la transición de `zoho-tickets` | Documentos repetidos | Dry-run comparativo y desactivar la carpeta local (F7.4) |
| Lentitud en buzones y carpetas grandes | Corridas de horas | `since_days`, límite `--max-subidas` por fuente, `version_tag` para no descargar |
| El VPS no alcanza la LAN (SMB) | SMB inviable desde el servidor | Ejecutar `sync_bot` dentro de la LAN o usar VPN (documentado en F1.4) |

---

## 5. Definición de «hecho» por fuente

1. Adaptador con tests de fixtures (paginación, auth expirada, rate limit,
   recurso inexistente, nombres con tildes) y `pytest` en verde.
2. «Probar conexión» funciona y los errores son legibles y no contienen
   secretos.
3. Corrida real en dry-run y luego real contra una cuenta de prueba; la
   segunda corrida no re-sube nada.
4. `--borrar-huerfanos` no toca lo subido por la fuente.
5. Los resultados aparecen en `ultima_sync.json`, en el dashboard y en
   Telegram.
6. Guía de configuración publicada; `.env.example`, `requirements.txt` y
   `build.spec` actualizados.

## 6. Siguiente paso inmediato

1. **Hoy:** enviar a ambos clientes la lista de accesos de §1.1 (es lo que
   más tarda) y agendar la llamada con el cliente de Zoho para generar el
   refresh token.
2. Cerrar D2–D7 (hay recomendación para cada una).
3. Abrir la rama `feature/guardas-borrado` e implementar F1.1–F1.5. Esto es
   obligatorio antes de conectar SharePoint o Zoho a producción.
4. En paralelo, `feature/sync-programada` con F2.
