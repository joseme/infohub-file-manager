# Guía: carpetas de red (SMB / NAS) como fuente de InfoHub

Opción A de `docs/integracion_smb.md`: se monta el recurso compartido dentro de
la carpeta observada y el File Manager lo trata como una carpeta local. No
requiere código nuevo; lo que sí es obligatorio es declarar el montaje en
`montajes_requeridos` para que una caída del NAS no borre documentos en InfoHub.

## 1. Requisitos

- Cuenta de servicio del NAS/dominio **de solo lectura** sobre el recurso.
- Linux: paquete `cifs-utils` (`sudo apt install cifs-utils`).
- Red: puerto TCP **445** abierto entre el equipo del File Manager y el NAS.
  Si el File Manager corre en el VPS y el NAS está en la LAN del cliente, hace
  falta una VPN o ejecutar `sync_bot.py` en un equipo dentro de esa LAN.
- SMB **3.x**. No usar SMB1 (`vers=1.0`): es inseguro.

## 2. Linux (fstab)

Archivo de credenciales, legible solo por root:

```bash
sudo mkdir -p /etc/infohub
sudo tee /etc/infohub/smb.cred >/dev/null <<'EOF'
username=usuario_servicio
password=CAMBIAR
domain=EMPRESA
EOF
sudo chmod 600 /etc/infohub/smb.cred
```

Punto de montaje **dentro** de la carpeta observada. Cada subcarpeta del
recurso pasa a ser un workspace, igual que una carpeta local:

```bash
mkdir -p /home/jose/Documentos/Infohub/Legal
```

Línea de `/etc/fstab` (todo en una línea):

```
//nas.local/legal  /home/jose/Documentos/Infohub/Legal  cifs  credentials=/etc/infohub/smb.cred,uid=jose,gid=jose,iocharset=utf8,vers=3.0,ro,_netdev,nofail  0  0
```

| Opción | Por qué |
|---|---|
| `ro` | El File Manager nunca debe modificar el origen |
| `vers=3.0` (o `3.1.1`) | Fuerza SMB3; se rechaza SMB1 |
| `iocharset=utf8` | Nombres con tildes y ñ |
| `_netdev,nofail` | Espera a la red y no bloquea el arranque si el NAS no responde |
| `uid`/`gid` | Archivos legibles por el usuario que ejecuta el bot |

Montar y comprobar:

```bash
sudo mount -a
findmnt /home/jose/Documentos/Infohub/Legal     # debe mostrar cifs
ls /home/jose/Documentos/Infohub/Legal
```

## 3. Declarar el montaje (obligatorio)

Si el NAS cae, el punto de montaje queda como una **carpeta vacía** y todo el
workspace parecería huérfano. Para que el borrado se bloquee siempre en ese
caso, añade la ruta a `montajes_requeridos`:

- Bot (`sync_bot.json`):
  ```json
  "montajes_requeridos": ["/home/jose/Documentos/Infohub/Legal"]
  ```
- Panel (`config.json`, se edita a mano porque no está en el diálogo):
  ```json
  "montajes_requeridos": ["/home/jose/Documentos/Infohub/Legal"]
  ```

Se puede declarar el punto de montaje o una carpeta superior. Cualquier carpeta
que quede por debajo de un montaje declarado y no montado queda protegida, y
`--forzar-borrado` **no** salta esta guarda.

Además, aunque el montaje no esté declarado, las guardas generales bloquean el
borrado si la carpeta aparece vacía o si se borraría más del 50 % del workspace
(`umbral_borrado_pct`, más de `minimo_borrado` documentos).

Si `sync_bot.json` lista las carpetas explícitamente en `carpetas`, añade
también la carpeta montada.

## 4. Windows

- Mapear una unidad (`net use I: \\nas.local\legal /persistent:yes`) o usar la
  ruta UNC directamente. `pathlib` acepta `\\nas.local\legal`.
- `os.path.ismount` reconoce las raíces UNC y las unidades, así que se pueden
  declarar en `montajes_requeridos` (`"I:\\"` o `"\\\\nas.local\\legal"`).
- Usar una cuenta de solo lectura en el recurso compartido.

## 5. Verificación (antes de activar el borrado programado)

1. `./venv/bin/python sync_bot.py --dry-run --carpetas "Legal" --sin-telegram`:
   las subcarpetas aparecen como workspaces y se listan los archivos.
2. Desmontar (`sudo umount /home/jose/Documentos/Infohub/Legal`) y repetir con
   `--borrar-huerfanos --dry-run`. El resumen debe mostrar `⚠ BORRADO
   BLOQUEADO: … no está montada`.
3. Volver a montar y ejecutar la corrida real.
4. Modificar un archivo en el NAS: se vuelve a subir. Si solo se hace `touch`,
   no se vuelve a subir (el bot compara por sha256).

## 6. Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| `mount error(13): Permission denied` | Credenciales o dominio incorrectos |
| `mount error(95): Operation not supported` | El NAS no admite la versión SMB pedida; probar `vers=3.1.1` o `vers=2.1` (nunca `1.0`) |
| `Host is down` / timeout | Puerto 445 bloqueado (firewall, VPN, ISP) |
| Nombres con `?` en lugar de tildes | Falta `iocharset=utf8` |
| El bot no ve archivos | `uid`/`gid` incorrectos o carpeta no listada en `carpetas` |
