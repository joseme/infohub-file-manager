ANALISIS TECNICO: FUENTE DE CORREO ELECTRONICO
InfoHub File Manager

1. RESUMEN EJECUTIVO
--------------------
El correo electronico es la fuente documental mas comun en despachos legales,
seguros y areas tributarias. Muchos documentos oficiales (resoluciones,
facturas electronicas, polizas, notificaciones judiciales) llegan exclusivamente
como adjuntos de correo. Integrar un buzon como fuente de datos permite que
InfoHub procese automaticamente esos adjuntos y los envie al workspace
adecuado sin intervencion manual.

2. PROTOCOLOS Y APIS DISPONIBLES
---------------------------------

Opcion A - IMAP (protocolo estandar):
- Servidor: imap.gmail.com, outlook.office365.com, etc.
- Ventaja: universal, no requiere registrar app en portal de desarrolladores.
- Desventaja:
  * Gmail bloqueo el acceso por contraseña basica en mayo de 2022.
  * Office 365 esta deprecando la autenticacion basica.
  * Requiere contraseñas de aplicacion o OAuth2 IMAP (complejo).

Opcion B - Microsoft Graph API (recomendado para Exchange / Office 365):
- Endpoint: /users/{id}/messages, /users/{id}/mailFolders
- Permisos: Mail.Read (app-only) o Mail.ReadWrite
- Ventaja: acceso moderno, seguro, sin problemas de autenticacion basica.
- Desventaja: solo cubre Microsoft 365.

Opcion C - Gmail API (recomendado para Gmail):
- Requiere OAuth2 con scope https://www.googleapis.com/auth/gmail.readonly
- Ventaja: oficial, estable, permite filtros avanzados.
- Desventaja: requiere consentimiento del usuario la primera vez.

3. ARQUITECTURA PROPUESTA
--------------------------

Se crea un modulo 'email_adapter.py' que implementa la interfaz comun
'AbstractSourceAdapter' y ofrece tres backends internos:
- IMAPEmailBackend
- GraphEmailBackend
- GmailAPIBackend

El usuario elige el backend en configuracion; el resto del flujo es identico.

4. DATOS DE CONFIGURACION NECESARIOS
-------------------------------------

Campos para 'config.json' y '.env.example':
- 'email_source_enabled': bool
- 'email_backend': select entre 'imap', 'graph', 'gmail'
- 'email_server' (solo IMAP): ej. 'outlook.office365.com'
- 'email_port' (solo IMAP): 993 por defecto
- 'email_username': direccion de correo
- 'email_password' (IMAP) o token OAuth2 (Graph/Gmail)
- 'email_client_id' (Graph/Gmail)
- 'email_client_secret' (Graph/Gmail)
- 'email_tenant_id' (Graph)
- 'email_folder': carpeta a monitorear, por defecto 'INBOX'
- 'email_since_days': int, solo leer correos de los ultimos N dias
- 'email_mark_processed': bool, mover correos a carpeta 'InfoHub/Procesados'
- 'email_max_attachment_size_mb': int
- 'email_allowed_extensions': lista, ej. ['.pdf', '.xml', '.docx']

5. LOGICA DE SINCRONIZACION
----------------------------

Paso 1 - Autenticacion:
- IMAP: login con usuario y contraseña/app-password; iniciar TLS.
- Graph: obtener token OAuth2 con Mail.Read.
- Gmail: obtener token OAuth2 con gmail.readonly.

Paso 2 - Listado de mensajes:
- IMAP: search UNSEEN SINCE date o ALL SINCE date.
- Graph: GET /users/{user}/mailFolders/{folder}/messages?$filter=receivedDateTime ge ...
- Gmail: users().messages().list(q='has:attachment newer_than:7d')

Paso 3 - Descarga de adjuntos:
- IMAP: para cada message part con disposition 'attachment', descargar payload.
- Graph: GET /messages/{id}/attachments y luego /attachments/{id}/$value.
- Gmail: GET /messages/{id}/attachments/{attachmentId} con base64url.

Paso 4 - Determinar workspace destino:
- Regla principal por remitente: facturas@hacienda.go.cr -> workspace 'Tributacion'.
- Regla secundaria por asunto: [Seguros] -> workspace 'Seguros'.
- Regla terciaria por carpeta IMAP: INBOX/Clientes/A -> workspace 'A'.
- Fallback: workspace por defecto 'Correo'.

Paso 5 - Guardar temporal y subir a InfoHub:
- Guardar adjunto en directorio temporal con nombre unico.
- Llamar a 'upload_file_to_workspace()' del motor existente.
- Eliminar temporal si la subida fue exitosa.

Paso 6 - Registro de estado:
- Clave en 'estado_sync.json': 'EMAIL:{message_id}:{filename}'.
- Se almacena: hash sha256 del adjunto, fecha de recepcion, remitente, asunto.

6. GESTION DE DUPLICADOS Y REPROCESAMIENTO
-------------------------------------------

- Usar 'Message-ID' del correo + nombre del adjunto como identificador unico.
- Si 'email_mark_processed' es true, mover el correo a carpeta 'InfoHub/Procesados'
  despues de procesar todos sus adjuntos exitosamente.
- Si un adjunto cambio (raro en correo), se detecta por hash sha256 distinto.
- Para evitar re-descargar todo el buzon historico, limitar por 'email_since_days'.

7. SEGURIDAD Y CREDENCIALES
----------------------------

- Nunca escribir contraseñas en texto plano en 'config.json'.
- Preferir variables de entorno o sistema de keyring.
- Para OAuth2, almacenar solo 'refresh_token' (no access_token a largo plazo).
- Usar STARTTLS/SSL en IMAP; rechazar conexion insegura.
- Validar extensiones y tamanos antes de descargar para evitar malware pesado.

8. FILTRADO Y CLASIFICACION
----------------------------

Filtros recomendados por defecto:
- Ignorar correos en papelera o spam.
- Ignorar adjuntos con extensiones peligrosas: .exe, .bat, .js, .zip sospechosos.
- Limitar tamanio de adjunto configurable (default 25 MB).
- Opcion de whitelist de remitentes o dominios.

Ejemplo de reglas de clasificacion:
- Remitente contiene 'hacienda.go.cr' -> workspace 'Guias Hacienda CR'
- Asunto contiene 'jurisprudencia' -> workspace 'Jurisprudencia'
- Remitente contiene 'nseguros.com' -> workspace 'Legislacion Seguros CR'
- Todo lo demas -> workspace 'Correo General'

9. CONSIDERACIONES ESPECIALES
------------------------------

- Correos con cuerpo HTML y archivos inline: distinguir 'attachment' de 'inline'.
  Solo procesar 'attachment' por defecto.
- Correos con firma digital (.p7m, .eml): decidir si se suben tal cual o se
  extrae contenido.
- Mensajes MIME multiparte: iterar recursivamente todas las partes.
- Codificaciones de nombres de archivo: RFC 2047, RFC 2231.
- Rate limiting: Graph y Gmail tienen cuotas; IMAP menos restrictivo pero puede
  desconectar por inactividad.

10. IMPACTO EN LA UI
---------------------

- Nueva seccion «Correo Electronico» en el panel de configuracion.
- Boton «Probar conexion» que lista las ultimas 5 cabeceras sin descargar.
- Tabla de reglas de clasificacion: remitente/asunto -> workspace.
- Indicador de ultima sincronizacion de correo.

11. PRUEBAS SUGERIDAS
----------------------

- Correo con un solo PDF.
- Correo con multiples adjuntos.
- Correo sin adjuntos (debe ignorarse).
- Nombre de archivo con caracteres especiales (tildes, espacios).
- Correo grande con adjunto mayor al limite configurado.
- Token expirado: verificar refresco automatico.
- Buzon vacio: no debe fallar.

12. DEPENDENCIAS
-----------------

- IMAP: solo biblioteca estandar 'imaplib' y 'email'.
- Graph: 'msgraph-sdk-python' o 'requests' con 'msal'.
- Gmail: 'google-auth-oauthlib', 'google-api-python-client'.

13. DIFERENCIAS VS FUENTES CLOUD YA ANALIZADAS
-----------------------------------------------

- SharePoint/OneDrive/Google Drive son repositorios de archivos; el correo es
  un flujo de eventos temporales.
- El correo requiere clasificacion inteligente por metadatos (remitente/asunto)
  para determinar el workspace.
- Los archivos de correo tienen duplicidad por naturaleza (mismo adjunto enviado
  a varios destinatarios); el Message-ID ayuda a deduplicar.
