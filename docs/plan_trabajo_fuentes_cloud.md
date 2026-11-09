PLAN DE TRABAJO: IMPLEMENTACION DE FUENTES EXTERNAS
InfoHub File Manager - SharePoint, OneDrive y Google Drive

OBJETIVO
--------
Extender InfoHub File Manager para sincronizar archivos desde fuentes cloud
(SharePoint, OneDrive, Google Drive) ademas de las carpetas locales actuales.

FASES DEL PROYECTO
------------------

FASE 1: PREPARACION Y BASE (Semana 1)
---------------------------------------

Tarea 1.1: Auditoria del codigo actual
- Revisar app.InfoHubFileManager.scan_files() y sort_files()
- Identificar puntos de insercion para adaptadores externos
- Documentar flujo de estado_sync.json

Tarea 1.2: Diseno de la arquitectura de adaptadores
- Crear base class AbstractSourceAdapter en adapters/base_adapter.py
- Definir interfaz comun:
  * authenticate() -> bool
  * list_files(folder_path) -> Iterator[FileInfo]
  * download_to_temp(file_id) -> Path
  * get_file_hash(file_id) -> str
  * resolve_workspace(file_path) -> str

Tarea 1.3: Extension de configuracion
- Modificar FIELDS_SCHEMA en config_manager.py
- Agregar UI para credenciales cloud en app.py
- Actualizar .env.example con variables nuevas

Entregables:
- adapters/base_adapter.py con interfaz definida
- Campos de configuracion en UI funcionando
- Documento de arquitectura tecnica

FASE 1.5: CORREO ELECTRONICO (Semana 1.5)
------------------------------------------

Tarea 1.5.1: Diseno del email_adapter.py
- Definir tres backends: IMAP, Microsoft Graph, Gmail API
- Clasificacion por remitente/asunto/carpeta
- Manejo de Message-ID y deduplicacion

Tarea 1.5.2: Implementacion de IMAP
- Soporte basico para Outlook/Gmail con contraseñas de aplicacion
- Descarga de adjuntos con manejo de RFC 2047
- Reglas de clasificacion configurables

Tarea 1.5.3: Implementacion de Microsoft Graph Mail
- Permisos Mail.Read
- Listado de mensajes con filtros por fecha
- Descarga de fileAttachments con /$value

Tarea 1.5.4: Implementacion de Gmail API
- OAuth2 desktop flow
- Filtro 'has:attachment newer_than:7d'
- Decodificacion base64url de adjuntos

Entregables:
- adapters/email_adapter.py funcional
- Reglas de clasificacion por remitente/asunto
- Pruebas con correos reales

FASE 1.6: ZOHO (Semana 1.6)
-------------------------------

Tarea 1.6.1: Diseno del zoho_adapter.py
- Tres backends: Desk, CRM, WorkDrive
- Manejo de data centers regionales (.com, .eu, .in)
- Autenticacion OAuth2 self-client con refresh token

Tarea 1.6.2: Implementacion de Zoho Desk
- Listar tickets y adjuntos
- Descargar attachments por ticketId
- Clasificacion por departamento, etiquetas y remitente

Tarea 1.6.3: Implementacion de Zoho CRM
- Listar registros por modulo (Cases, Leads, Deals)
- Obtener adjuntos de cada registro
- Mapeo de modulo a workspace

Tarea 1.6.4: Implementacion de Zoho WorkDrive
- Listar archivos y carpetas de un workspace
- Recorrido recursivo
- Mapeo de carpetas a workspaces

Entregables:
- adapters/zoho_adapter.py funcional
- Soporte para Desk, CRM y WorkDrive
- Pruebas con cuenta de desarrollo Zoho

FASE 1.7: SMB / CARPETAS DE RED (Semana 1.7)
-------------------------------------------

Tarea 1.7.1: Opcion A - montaje cifs en solo lectura
- Documentar fstab y archivo de credenciales (600)
- Probar que scan_files reconoce las subcarpetas montadas

Tarea 1.7.2: Guarda anti-falso-vacio en sync_bot.py y app.py
- Verificar raiz accesible / os.path.ismount antes de escanear
- Abortar borrar_huerfanos si el listado cae a cero o bajo umbral

Tarea 1.7.3 (opcional): Opcion B - smb_source.py con smbprotocol
- Solo si hay equipos sin montaje posible (Windows/exe)
- Cambios por (size, mtime) y confirmacion por sha256

Entregables:
- Guia de montaje, guarda anti-borrado, adaptador SMB opcional

FASE 2: IMPLEMENTACION DE SHAREPOINT (Semana 2-3)
--------------------------------------------------

Tarea 2.1: Modulo sharepoint_adapter.py
- Implementar autenticacion OAuth2 (Client Credentials Flow)
- Integrar con Microsoft Graph API
- Metodos: get_site_id(), get_drive_id(), list_drive_items()

Tarea 2.2: Manejo de archivos y carpetas
- Recorrido recursivo de carpetas SharePoint
- Descarga temporal de archivos antes de subir a InfoHub
- Mapeo de subcarpetas a workspaces (usando workspace_map)

Tarea 2.3: Gestion de estado
- Usar eTag como identificador unique
- Prefijo "SP:" en estado_sync.json
- Deteccion de cambios sin re-descarga completa

Tarea 2.4: Testing y validacion
- Casos de prueba con sitio de desarrollo
- Manejo de errores de red y token expirado
- Rate limiting y backoff exponencial

Entregables:
- adapters/sharepoint_adapter.py funcional
- Tests unitarios con cobertura > 80%
- Documento de configuracion para usuarios

FASE 3: IMPLEMENTACION DE ONEDRIVE (Semana 4)
----------------------------------------------

Tarea 3.1: Modulo onedrive_adapter.py
- Implementar autenticacion (app-only para business, delegated para personal)
- Endpoints Graph API especificos de OneDrive
- Soporte para OneDrive Personal y OneDrive for Business

Tarea 3.2: Diferencias con SharePoint
- Manejo de delta links para cambios incrementales
- Resolucion de rutas por GUID en lugar de path
- IDs de archivo diferentes a paths de SharePoint

Tarea 3.3: Configuracion dual
- Deteccion automatica: business vs personal
- UI para credenciales especificas
- Prefijo "OD:" en estado_sync.json

Entregables:
- adapters/onedrive_adapter.py funcional
- Soporte completo Personal + Business
- Guia de configuracion

FASE 4: IMPLEMENTACION DE GOOGLE DRIVE (Semana 5)
--------------------------------------------------

Tarea 4.1: Modulo google_drive_adapter.py
- Autenticacion Service Account (JSON key) y OAuth Desktop
- Integracion con Google Drive API v3
- Metodos: files.list(), changes.list(), files.get()

Tarea 4.2: Estrategia de deteccion de cambios
- Implementar polling con changes.list()
- Almacenar startPageToken entre corridas
- Opcional: soporte basico de webhooks

Tarea 4.3: Manejo de tipos especiales
- Exportar Google Docs/Sheets/Slides a formatos compatibles (PDF)
- Ignorar archivos en papelera (trashed=true)
- Resolver shortcuts a archivo real

Tarea 4.4: Testing especial
- Rate limiting de Google (1000 queries/100s)
- Manejo de archivos compartidos vs propios
- Archivos grandes (>100MB)

Entregables:
- adapters/google_drive_adapter.py funcional
- Soporte Service Account y OAuth
- Exportacion automatica de Google Workspace files

FASE 5: INTEGRACION Y UI (Semana 6)
------------------------------------

Tarea 5.1: Integracion en app.py
- Modificar scan_files() para soportar multiples fuentes
- Selector de fuente en UI (local, SharePoint, OneDrive, Google Drive)
- Progress bar para operaciones cloud (mas lentas)

Tarea 5.2: Mejoras en sync_bot.py
- Soporte para --fuente argumento
- Ejecucion desatendida de fuentes cloud
- Logging detallado de errores de API

Tarea 5.3: Gestion de credenciales
- Almacenamiento seguro de tokens (keyring opcional)
- Refresco automatico de tokens expirados
- Validacion de permisos antes de sincronizar

Entregables:
- UI con selector de fuentes funcionando
- sync_bot.py actualizado con soporte cloud
- Flujo completo de autenticacion y sincronizacion

FASE 6: DOCUMENTACION Y DEPLOY (Semana 7)
------------------------------------------

Tarea 6.1: Documentacion de usuario
- Guia paso a paso para cada plataforma
- Troubleshooting de errores comunes
- Configuracion de Service Accounts y Apps

Tarea 6.2: Actualizacion de README
- Nueva seccion de fuentes cloud
- Badges de estado (SharePoint, OneDrive, Google Drive)
- Requisitos de cuentas y permisos

Tarea 6.3: Deployment
- Actualizar requirements.txt
- Script de instalacion de dependencias
- Docker compose actualizado (si aplica)

Entregables:
- Documentacion completa en español
- README.md actualizado
- Release notes para usuarios

CRONOGRAMA RESUMEN
------------------
| Fase | Semana | Enfoque |
|------|--------|---------|
| 1    | 1      | Base y arquitectura |
| 2    | 2-3    | SharePoint |
| 3    | 4      | OneDrive |
| 4    | 5      | Google Drive |
| 5    | 6      | Integracion UI |
| 6    | 7      | Docs y deploy |

DEPENDENCIAS CRITICAS
---------------------
- Python 3.10+
- msgraph-sdk-python (SharePoint/OneDrive)
- google-auth, google-api-python-client (Google Drive)
- Credenciales de Azure AD y Google Cloud validas
- Acceso de prueba a sitios/carpetas de cada plataforma

ESTADO INICIAL
--------------
- Documentos de analisis completos en docs/
- Interfaz base de adaptadores pendiente
- Credenciales aun no configuradas
- Testing requerira cuentas de desarrollo

PRIORIDAD RECOMENDADA
---------------------
Comenzar con SharePoint (Fase 2) ya que:
1. Usa mismo backend Graph que OneDrive (reutilizable)
2. Autenticacion app-only es mas simple que OAuth de personal
3. Es el caso de uso mas comun en entornos empresariales

SIGUIENTE PASO SUGERIDO
-----------------------
Implementar Tarea 1.2: Crear adapters/base_adapter.py con la interfaz
abstracta que compartiran todos los adaptadores cloud.


FUENTES EVALUADAS Y NO PLANIFICADAS (FASES FUTURAS)
---------------------------------------------------
- Dropbox / Box: API similar a las de nube ya analizadas; reutilizan la interfaz
  de adaptadores. Sin analisis detallado todavia.
- Notion / Confluence: contenido como paginas, requiere exportar a PDF/Markdown.
  Sin analisis detallado todavia.
