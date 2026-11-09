ANALISIS TECNICO: FUENTE SMB (CARPETAS DE RED / NAS)
InfoHub File Manager

1. RESUMEN
----------
SMB/CIFS es el protocolo de las carpetas compartidas de Windows, Samba y NAS
(Synology, QNAP). Es la fuente tipica de entornos on-premise que no usan nube.
El File Manager hoy solo lee rutas locales con pathlib (scan_files y sort_files
en app.py, y sync_bot.py). Hay dos formas de cubrir SMB; la primera casi no
requiere codigo.

2. OPCION A - MONTAJE DEL SISTEMA OPERATIVO (recomendada como primer paso)
---------------------------------------------------------------------------
Montar el recurso compartido dentro de la carpeta observada. El File Manager lo
ve como una carpeta local normal, sin cambios en el codigo.

Ejemplo Linux (/etc/fstab):
  //nas.local/legal  /home/jose/Documentos/Infohub/Legal  cifs  credentials=/etc/infohub/smb.cred,uid=jose,gid=jose,iocharset=utf8,vers=3.0,ro,_netdev,nofail  0  0

Archivo de credenciales /etc/infohub/smb.cred (permisos 600, root):
  username=usuario_servicio
  password=...
  domain=EMPRESA

- Montar en solo lectura ('ro'): el File Manager nunca debe modificar el origen.
- Cada subcarpeta montada dentro de 'Infohub*' se convierte en un workspace, igual
  que una carpeta local (regla actual de scan_files).
- Windows: mapear unidad de red (net use) o usar ruta UNC; pathlib acepta
  \\servidor\recurso.
- Ventajas: cero dependencias, cero codigo, reutiliza estado_sync.json (sha256) y
  toda la logica de duplicados existente.
- Desventajas: requiere permisos de root para montar; si el montaje cae, la
  carpeta aparece vacia y la limpieza de huerfanos podria borrar documentos en
  InfoHub (ver riesgo 6.1).

3. OPCION B - CLIENTE SMB EN PYTHON (adaptador)
-----------------------------------------------
Solo si no se puede montar (equipo sin privilegios, ejecutable PyInstaller en
Windows, multiples servidores configurables desde la UI).

- Libreria: 'smbprotocol' (paquete 'smbclient'), SMB2/SMB3, Python puro, soporta
  cifrado SMB3 y Kerberos/NTLM. Alternativa: 'pysmb' (SMB1/2, menos mantenida).
- API de alto nivel: register_session(servidor, username, password),
  scandir(r"\\servidor\recurso\ruta"), open_file(ruta, mode="rb"), stat().
- Modulo nuevo: smb_source.py con la misma interfaz que los otros adaptadores:
  authenticate(), list_files(base) -> (ruta_relativa, size, mtime),
  download_to_temp(ruta) -> Path.
- Mapeo a workspaces: primer nivel bajo la ruta base = workspace (igual que
  carpetas locales).

4. CONFIGURACION (solo Opcion B)
---------------------------------
Campos para config.json / FIELDS_SCHEMA:
- smb_enabled: bool
- smb_server: ej. 'nas.local'
- smb_share: ej. 'legal'
- smb_base_path: ej. 'Infohub'
- smb_username, smb_password (tipo password; preferir variable de entorno)
- smb_domain: opcional
- smb_encrypt: bool (SMB3)
- smb_max_file_size_mb: int
Variables .env.example: SMB_USERNAME, SMB_PASSWORD.

5. DETECCION DE CAMBIOS
------------------------
SMB no ofrece hash remoto ni delta. Estrategia:
- Comparar (size, mtime) contra el estado guardado; solo si difieren, descargar y
  calcular sha256 para confirmar cambio real (evita re-subidas por touch).
- Clave en estado_sync.json: 'SMB:{servidor}/{recurso}/{ruta_relativa}'.
- Con la Opcion A el flujo actual (sha256 local) ya funciona sin cambios.
- Cuidado con diferencias de zona horaria y resolucion de mtime entre NAS y host.

6. RIESGOS Y CONSIDERACIONES
-----------------------------
6.1 Borrado por falso vacio (critico en ambas opciones):
- Si el servidor no responde o el montaje cae, el listado sale vacio y
  'borrar_huerfanos' podria eliminar documentos en InfoHub.
- Mitigacion: abortar la limpieza si la raiz no es accesible o si el listado
  cae a cero/mas del X% respecto de la corrida anterior; verificar punto de
  montaje con os.path.ismount antes de escanear.
6.2 Credenciales: cuenta de servicio de solo lectura; nunca en config.json en
    claro; archivo de credenciales 600.
6.3 Archivos bloqueados o en uso: reintentar y omitir sin abortar la corrida.
6.4 Nombres: NAS suelen ser case-insensitive; Linux es case-sensitive. Normalizar
    con workspace_map.canonical al comparar nombres de carpeta.
6.5 Rutas largas y caracteres especiales (Windows 260 chars, tildes): usar
    iocharset=utf8.
6.6 Rendimiento: listados recursivos de miles de archivos en LAN lenta; limitar
    por corrida (--max-subidas existente) y cachear (size, mtime).
6.7 Red: puerto TCP 445; en VPN/VPS puede estar bloqueado. Si el File Manager
    corre en el VPS (65.75.202.27) y el NAS esta en la LAN, hace falta VPN o
    ejecutar el sync_bot dentro de la LAN.
6.8 Cifrado: preferir SMB 3.x y rechazar SMB1 (inseguro).

7. PRUEBAS SUGERIDAS
---------------------
- Montaje ro: scan_files ve subcarpetas como workspaces.
- Desmontar a mitad de corrida: no debe borrar nada en InfoHub.
- Archivo modificado: se re-sube; archivo solo 'touch': no se re-sube.
- Nombre con tildes y espacios.
- Credenciales invalidas: error claro, sin traza con la contraseña.
- Opcion B: share con SMB3 cifrado; servidor inalcanzable (timeout).

8. RECOMENDACION
-----------------
- Fase 1: Opcion A (montaje) + guarda anti-falso-vacio en sync_bot.py. Esfuerzo
  bajo (documentacion y una verificacion), cubre el caso Linux/NAS.
- Fase 2 (solo si se necesita): smb_source.py con smbprotocol para Windows/exe
  o configuracion desde la UI. Depende de la interfaz comun de adaptadores
  definida en la Fase 1 del plan.

Fuentes: github.com/jborean93/smbprotocol (documentacion y ejemplos
high-level/directory-management.py).
