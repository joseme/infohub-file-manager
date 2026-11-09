ANALISIS TECNICO: FUENTE ZOHO
InfoHub File Manager

1. RESUMEN EJECUTIVO
--------------------
En 'sync_bot.json' ya existe una carpeta llamada 'zoho-tickets', lo que indica
que el proyecto actualmente recibe archivos provenientes de Zoho Desk de forma
manual o a traves de otro proceso externo. Integrar Zoho directamente como
fuente documental eliminaria ese paso manual y permitiria sincronizar
automaticamente adjuntos de tickets, documentos de CRM y archivos de WorkDrive
hacia los workspaces de InfoHub.

2. PRODUCTOS ZOHO RELEVANTES
-----------------------------

2.1 Zoho Desk
- Gestion de tickets de soporte al cliente.
- Endpoint principal: /api/v1/tickets
- Adjuntos disponibles en: /api/v1/tickets/{ticketId}/attachments
- Autenticacion: OAuth2 con scope 'Desk.tickets.ALL' o 'Desk.tickets.READ'.

2.2 Zoho CRM
- Registros de clientes, oportunidades, casos, facturas.
- Endpoint: /crm/v8/{module_api_name}/{record_id}/Attachments
- Modulos comunes: Leads, Contacts, Accounts, Cases, Deals, Invoices.
- Autenticacion: OAuth2 con scope 'ZohoCRM.modules.attachments.READ'.

2.3 Zoho WorkDrive
- Almacenamiento de archivos en la nube (equivalente a Google Drive/OneDrive).
- Endpoint base: /workdrive/api/v1
- Soporta archivos, carpetas, equipos (Workspaces) y equipos de trabajo.
- Autenticacion: OAuth2 con scope 'WorkDrive.workspace.ALL'.

3. AUTENTICACION
-----------------

Zoho utiliza OAuth2 con particularidades importantes:
- Cuentas regionales: .com, .eu, .in, .com.cn, .com.au
- El dominio de autorizacion y de API debe coincidir con la region de la cuenta.
- En 'config.json' se debe agregar 'zoho_dc' con valores como 'com', 'eu', 'in'.

Flujo recomendado para servidores (self-client):
1. Registrar aplicacion en Zoho API Console.
2. Generar 'Client ID' y 'Client Secret'.
3. Usar flujo 'Self Client' para obtener refresh token sin intervencion del usuario.
4. Almacenar refresh token de forma segura.
5. Usar refresh token para obtener access token automaticamente.

Endpoints de token:
- Cuentas .com: https://accounts.zoho.com/oauth/v2/token
- Cuentas .eu: https://accounts.zoho.eu/oauth/v2/token
- Cuentas .in: https://accounts.zoho.in/oauth/v2/token

4. ARQUITECTURA PROPUESTA
--------------------------

Se crea un modulo 'zoho_adapter.py' que implementa la interfaz comun
'AbstractSourceAdapter' y ofrece tres sub-adaptadores internos:
- ZohoDeskAdapter
- ZohoCRMAdapter
- ZohoWorkDriveAdapter

El administrador elige el producto y los parametros de conexion.

5. CONFIGURACION NECESARIA
---------------------------

Campos para 'config.json':
- 'zoho_enabled': bool
- 'zoho_product': select entre 'desk', 'crm', 'workdrive'
- 'zoho_dc': select entre 'com', 'eu', 'in', 'com.cn', 'com.au'
- 'zoho_client_id': string
- 'zoho_client_secret': password
- 'zoho_refresh_token': password
- 'zoho_org_id': string (requerido para Desk)
- 'zoho_department_id': string (opcional para Desk)
- 'zoho_module': string (solo CRM, ej. 'Cases', 'Leads', 'Deals')
- 'zoho_workdrive_team_id': string (solo WorkDrive)
- 'zoho_workdrive_workspace_id': string (solo WorkDrive)
- 'zoho_since_days': int
- 'zoho_max_file_size_mb': int
- 'zoho_allowed_extensions': lista

Variables de entorno en '.env.example':
- ZOHO_CLIENT_ID
- ZOHO_CLIENT_SECRET
- ZOHO_REFRESH_TOKEN
- ZOHO_DC

6. FLUJO DE SINCRONIZACION POR PRODUCTO
----------------------------------------

6.1 Zoho Desk
- Obtener lista de tickets actualizados desde 'zoho_since_days'.
- Para cada ticket, obtener adjuntos en /tickets/{id}/attachments.
- Descargar adjunto temporalmente.
- Determinar workspace por:
  * Departamento del ticket
  * Etiquetas (tags)
  * Asunto o campos personalizados
  * Remitente del ticket
- Subir a InfoHub y registrar estado con clave 'ZOHO:desk:{ticketId}:{attachmentId}'.

6.2 Zoho CRM
- Obtener registros del modulo configurado modificados recientemente.
- Para cada registro, obtener adjuntos en /{module}/{id}/Attachments.
- Descargar adjuntos.
- Determinar workspace por modulo (Cases -> Jurisprudencia, Deals -> Ventas, etc.).
- Subir a InfoHub con clave 'ZOHO:crm:{module}:{recordId}:{attachmentId}'.

6.3 Zoho WorkDrive
- Listar archivos de un workspace/equipo especifico.
- Recorrer carpetas recursivamente.
- Descargar archivos y subirlos a InfoHub.
- Mapeo de carpetas a workspaces igual que SharePoint/Google Drive.
- Clave de estado: 'ZOHO:wd:{fileId}'.

7. GESTION DE ESTADO Y DEDUPLICACION
-------------------------------------

- Usar IDs numericos de Zoho para tickets, registros y adjuntos.
- Prefijo en 'estado_sync.json': 'ZOHO:desk:', 'ZOHO:crm:', 'ZOHO:wd:'.
- Almacenar: fecha de ultima modificacion, hash sha256, nombre del archivo.
- Zoho Desk incluye 'createdTime' y 'modifiedTime' en tickets; usar para evitar
  re-procesamiento.

8. MANEJO DE ERRORES ESPECIFICOS
---------------------------------

- INVALID_ticket: ticket eliminado o sin permisos.
- DOWNLOAD_NOT_ALLOWED: adjunto es un enlace externo, no un archivo.
- RATE_LIMIT_EXCEEDED: Zoho limita segun edicion; implementar backoff.
- Token expirado: refrescar automaticamente con refresh token.
- Cuenta regional incorrecta: validar 'zoho_dc' antes de cada llamada.

9. SEGURIDAD
-------------

- No almacenar client secret en 'config.json' sin cifrar; preferir '.env'.
- El refresh token debe rotarse si se sospecha de exposicion.
- Limitar scopes al minimo necesario (READ en lugar de ALL si es posible).
- Validar extensiones de archivo descargadas.

10. CLASIFICACION A WORKSPACES
-------------------------------

Reglas sugeridas para despachos/seguros:
- Ticket de Departamento 'Soporte Tecnico' -> workspace 'Soporte'
- Ticket etiquetado 'Seguros' -> workspace 'Legislacion Seguros CR'
- Caso CRM de tipo 'Reclamacion' -> workspace 'Jurisprudencia Seguros CR'
- WorkDrive carpeta 'Tributacion' -> workspace 'Tributacion CR'

11. CONSIDERACIONES ESPECIALES
-------------------------------

- Zoho Desk permite adjuntos en comentarios, no solo en el ticket original.
  Se debe decidir si procesar adjuntos de comentarios tambien.
- CRM tiene un limite de 10MB por adjunto en algunas ediciones.
- WorkDrive soporta archivos grandes (hasta 5GB), pero InfoHub tiene su propio
  limite de subida.
- Zoho no siempre incluye 'Content-Type' correcto; inferir extension desde el
  nombre de archivo.

12. PRUEBAS SUGERIDAS
----------------------

- Conexion OAuth exitosa con refresh token.
- Listado de tickets con adjuntos.
- Descarga de adjunto de ticket.
- Descarga de adjunto de registro CRM.
- Listado recursivo de WorkDrive.
- Manejo de adjunto que es enlace externo (debe ignorarse).
- Rate limiting: backoff funciona.
- Cuenta regional incorrecta: error claro.

13. DEPENDENCIAS
-----------------

- 'requests' (probablemente ya en requirements.txt)
- Posiblemente 'zcrmsdk' para CRM si se prefiere SDK oficial
- Para WorkDrive no hay SDK oficial maduro; usar requests directamente

14. RELACION CON CARPETA 'zoho-tickets' EXISTENTE
-------------------------------------------------

La carpeta 'zoho-tickets' en 'sync_bot.json' puede mantenerse como mecanismo de
respaldo o transicion. Una vez activo 'zoho_adapter.py', el flujo recomendado
es desactivar esa carpeta local y sincronizar directamente desde Zoho Desk para
evitar duplicados.
