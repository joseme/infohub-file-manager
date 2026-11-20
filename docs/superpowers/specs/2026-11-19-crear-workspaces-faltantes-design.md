# Crear workspaces faltantes desde el panel — diseño

**Fecha:** 2026-11-19
**Estado:** aprobado

## Intención

El administrador crea una carpeta bajo `~/Documentos/Infohub/` y espera que el
panel cree el workspace correspondiente en InfoHub. Hoy la carpeta se descarta
en silencio porque `scan_files`, `sort_files` y `full_upload_and_clean` filtran
por `get_accessible_workspace_names` (solo workspaces que ya existen).

## Decisiones

- Se crea al **escanear**, al **ordenar** y en el **sync completo**; nunca en
  simulación (`simular=True` mantiene su contrato de no escribir).
- `POST /api/v1/workspace/new` con el nombre de la carpeta.
- No se intenta crear si la carpeta está fuera de `allowed_workspaces` (alcance
  del usuario SSO) ni si es un workspace protegido (`protected_workspaces`);
  esas siguen ocultas/omitidas como hoy.
- `401/403` → aviso "sin permiso de creación". Cualquier otro fallo (red, 5xx)
  → aviso con el detalle. El resultado de la operación pasa a `warning` y el
  mensaje se ve en snackbar y en el log (ya existe `log_operation`).
- Si el POST responde 200 pero la API key igual no ve el workspace, se avisa
  ("creado sin acceso") y la carpeta no se muestra.

## No objetivos

- No cambia `sync_bot.py` (ya crea workspaces con `crear_workspaces`).
- No crea workspaces desde el modo demo.
- No toca licencias ni permisos de InfoHub.

## Puntos abiertos para el implementador

- Reutilizar el idioma de los mensajes ya existente (ES fuente, EN espejo).
- Una prueba por caso: se crea, sin permiso, protegido, simulación.
