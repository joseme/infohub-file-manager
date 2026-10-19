#!/usr/bin/env python3
"""Bot de sincronización de ~/Documentos/Infohub con los workspaces de InfoHub.

Lee las subcarpetas de ~/Documentos/Infohub/ (configurables en sync_bot.json) y
sube a su workspace de InfoHub los archivos que faltan o que cambiaron desde la
última corrida. Con "borrar_huerfanos": true en sync_bot.json (o --borrar-
huerfanos en la corrida) también borra del workspace los documentos que ya no
tienen equivalente en la carpeta local.

El workspace destino se resuelve contra el servidor por nombre real
(workspace_map.WorkspaceResolver), usando alias locales como odoo -> odoo17.
Reutiliza el motor probado del panel (app.InfoHubFileManager): subida,
listado de documentos del workspace, borrado puntual y update-embeddings.

Pensado para correr después de los tres bots de normativa (cr-tributario 03:00,
cr-laboral 04:00, cr-seguros 05:00): cron domingos 06:30, y si alguno sigue
corriendo (flock de logs/actualizar.lock) el bot espera.

    ./venv/bin/python sync_bot.py                    # corrida completa
    ./venv/bin/python sync_bot.py --dry-run          # solo reporta, no sube
    ./venv/bin/python sync_bot.py --carpetas "zoho-tickets" --sin-telegram
    ./venv/bin/python sync_bot.py --max-subidas 50   # limita por corrida
    ./venv/bin/python sync_bot.py --sin-esperar-locks

Log en logs/sync_AAAAMMDD_HHMM.log, estado en logs/estado_sync.json (sha256 de
cada archivo ya subido) y resumen por Telegram (token en ~/.hermes/.env, chat
8239151265, igual que los otros bots).
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import logging
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from config_manager import ConfigManager          # noqa: E402
from app import InfoHubFileManager                # noqa: E402
from workspace_map import WorkspaceResolver, canonical   # noqa: E402

LOGS = BASE / "logs"
CONFIG_BOT = BASE / "sync_bot.json"

DEFAULTS_BOT = {
    "root": str(pathlib.Path.home() / "Documentos/Infohub"),
    "carpetas": [],
    "alias_workspaces": {},
    "excluir_sufijos": [".image_description", ".image_description.txt"],
    "extensiones_ignoradas": [".zip"],
    "max_intentos": 3,
    "borrar_huerfanos": False,
    "actualizar_cambiados": True,
    "crear_workspaces": True,
    "esperar_locks": [],
    "espera_max_min": 240,
    "telegram": True,
    "estado": "logs/estado_sync.json",
}

log = logging.getLogger("sync_bot")


# --- utilidades ---------------------------------------------------------------

def cargar_bot_config() -> dict:
    cfg = dict(DEFAULTS_BOT)
    try:
        cfg.update(json.loads(CONFIG_BOT.read_text(encoding="utf8")))
    except FileNotFoundError:
        print(f"Aviso: no existe {CONFIG_BOT.name}; se usan los valores por defecto")
    except ValueError as e:
        print(f"Error leyendo {CONFIG_BOT.name}: {e}")
    return cfg


def leer_env(ruta: pathlib.Path) -> dict:
    env = {}
    try:
        for line in ruta.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def telegram(texto: str):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or leer_env(BASE / ".env").get("TELEGRAM_BOT_TOKEN", "") \
        or leer_env(pathlib.Path.home() / ".hermes/.env").get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID") or leer_env(BASE / ".env").get("TELEGRAM_CHAT_ID", "") \
        or "8239151265"
    if not (tok and chat):
        print("Telegram: falta token o chat_id; no se envía")
        return
    datos = urllib.parse.urlencode({"chat_id": chat, "text": texto[:3900],
                                    "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=datos),
            timeout=30,
        ) as r:
            r.read()
        print("Telegram: resumen enviado")
    except Exception as e:
        print(f"Telegram: no se pudo enviar ({e})")


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_UUID_RE = re.compile(
    r"([-.](?:[0-9a-fA-F]{6,}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}))$"
)


def _sin_uuid(base: str) -> str:
    return _UUID_RE.sub("", base or "")


def coincide_remoto(base_servidor: str, remoto_local: str) -> bool:
    """Identidad entre un documento del servidor y un archivo local.

    Acepta dos formas, ambas con el uuid del servidor ya quitado y comparadas en
    forma canónica (minúsculas, sin acentos ni puntuación):

    - nombre calificado por carpeta: 'normativa__01-procedimiento__X.md' (lo que
      sube el bot, para que dos subcarpetas con el mismo nombre no colisionen);
    - nombre base suelto: 'X.md' (como subió el panel/scripts anteriores).

    Ojo: el matcher del panel compara por PREFIJO ('...75' matchea '...75.pdf'),
    lo que hacía que un .zip con el mismo número de factura que un .pdf ya subido
    se considerara presente y nunca se subiera.
    """
    c = canonical(_sin_uuid(base_servidor))
    return c == canonical(remoto_local) or c == canonical(remoto_local.split("__")[-1])


def remoto_existente(remotos, remoto_local: str):
    """Base del documento del servidor que corresponde al archivo local (o None)."""
    for b in remotos:
        if coincide_remoto(b, remoto_local):
            return b
    return None


def esperar_locks(rutas: list, max_min: int) -> float:
    """Espera a que los bots de normativa suelten su lock. Devuelve segundos esperados."""
    rutas = [pathlib.Path(r) for r in rutas if r]
    if not rutas:
        return 0.0
    t0 = time.time()
    avisado = False
    while True:
        ocupados = []
        for r in rutas:
            if not r.exists():
                continue
            fh = open(r, "w")
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                ocupados.append(r.parent.parent.name)
            finally:
                fh.close()
        if not ocupados:
            return time.time() - t0
        if (time.time() - t0) > max_min * 60:
            log.warning("Espera agotada (%s min) con locks ocupados: %s", max_min, ", ".join(ocupados))
            return time.time() - t0
        if not avisado:
            log.info("Esperando a que terminen: %s", ", ".join(ocupados))
            avisado = True
        time.sleep(30)


# --- sincronización ----------------------------------------------------------

def sincronizar_carpeta(mgr: InfoHubFileManager, resolver: WorkspaceResolver, carpeta: pathlib.Path,
                        bot_cfg: dict, estado: dict, dry: bool, max_subidas: int, restantes: list) -> dict:
    """Sincroniza una carpeta local con su workspace. Devuelve el resumen."""
    nombre = carpeta.name
    excl = tuple(bot_cfg["excluir_sufijos"])
    res = {"carpeta": nombre, "slug": None, "existe": False, "creado": False,
           "locales": 0, "subidos": 0, "actualizados": 0, "omitidos": 0, "adoptados": 0,
           "ignorados": [], "fallidos": [], "huerfanos": [], "errores": [], "embeddings": False}

    slug, existe = resolver.slug(nombre)
    res["slug"], res["existe"] = slug, existe
    # workspaces protegidos (protected_workspaces en config.json o PROTECTED_WORKSPACES):
    # se cargan fuera del file manager, así que no se sube ni se borra nada.
    # Se compara el slug ya resuelto, para que un alias (odoo -> odoo17) no los esquive.
    if slug in mgr.protected_workspaces or mgr.is_protected(nombre):
        res["protegido"] = True
        log.info("Workspace '%s' (%s) protegido: se omite", nombre, slug)
        return res
    if not existe:
        if not bot_cfg["crear_workspaces"] or dry:
            res["errores"].append(f"workspace no existe y crear_workspaces={bot_cfg['crear_workspaces']}")
            return res
        nuevo = resolver.crear(nombre)
        if not nuevo:
            res["errores"].append("no se pudo crear el workspace")
            return res
        slug, res["slug"], res["creado"] = nuevo, nuevo, True
        existe = True
        log.info("Workspace creado para '%s': %s", nombre, slug)
        resolver.refresh()  # indexa el workspace nuevo antes de la corrida

    # alcance del usuario/API key (si aplica)
    if not mgr.get_accessible_workspace_names([nombre]):
        res["errores"].append("el workspace no es accesible con la API key")
        return res

    docs = mgr.get_workspace_documents(nombre)
    remotos = set(docs.get("base_names", set()))
    doc_names = docs.get("doc_names", {})

    archivos = [f for f in sorted(carpeta.rglob("*"))
                if f.is_file() and not f.name.endswith(excl)]
    ignor_ext = {e.lower() for e in bot_cfg.get("extensiones_ignoradas", [])}
    locales = []
    for f in archivos:
        rel = mgr._rel_path(f, carpeta)
        (res["ignorados"] if f.suffix.lower() in ignor_ext else locales).append(rel)
    res["locales"] = len(locales)
    estado_ws = estado.setdefault(slug, {})

    for rel in locales:
        f = carpeta / rel
        remoto = mgr._remote_name(rel)
        try:
            st = f.stat()
            sha = sha256(f)
        except OSError as e:
            res["errores"].append(f"{rel}: {e}")
            continue
        previo = estado_ws.get(remoto)
        intentos_previos = previo.get("intentos", 0) if previo and previo.get("sha") == sha else 0
        if intentos_previos >= bot_cfg.get("max_intentos", 3):
            res["fallidos"].append(rel)  # ya falló N veces con el mismo contenido
            continue
        base_existente = remoto_existente(remotos, remoto)
        en_servidor = base_existente is not None
        if en_servidor and previo is None:
            # documento que ya estaba en el servidor (panel/otras vías): se adopta
            # como línea base para detectar cambios, sin volver a subirlo
            estado_ws[remoto] = {"sha": sha, "size": st.st_size, "adoptado": True}
            res["adoptados"] += 1
            continue
        cambio = previo is None or previo.get("sha") != sha or intentos_previos > 0

        if en_servidor and not cambio:
            res["omitidos"] += 1
            continue
        if en_servidor and not bot_cfg["actualizar_cambiados"]:
            res["omitidos"] += 1
            continue
        if dry:
            res["subidos" if not en_servidor else "actualizados"] += 1
            continue
        if restantes[0] <= 0:
            res["errores"].append("límite de subidas alcanzado (--max-subidas)")
            break
        restantes[0] -= 1

        # si cambió y ya está en el servidor, se borra la copia remota exacta y se sube la nueva
        if en_servidor and bot_cfg["actualizar_cambiados"]:
            exactos = [doc_names[b] for b in remotos
                       if b in doc_names and coincide_remoto(b, remoto)]
            if exactos:
                ok, cnt, errs = mgr.delete_documents(exactos)
                if ok:
                    remotos.difference_update({b for b in list(remotos) if coincide_remoto(b, remoto)})
                    doc_names = {k: v for k, v in doc_names.items() if v not in exactos}
                    mgr._base_name_cache.pop(nombre, None)
                else:
                    res["errores"].append(f"{rel}: no se pudo reemplazar ({errs[:1]})")
                    continue

        ok, omitido, msg = mgr.upload_file_to_workspace(
            f, nombre, workspace_folder=carpeta, skip_if_exists=False,
            # al reemplazar se conserva el nombre que ya tenía en el servidor
            remote_name=_sin_uuid(base_existente) if base_existente else None)
        if ok:
            res["actualizados" if en_servidor else "subidos"] += 1
            remotos.add(remoto)
            estado_ws[remoto] = {"sha": sha, "size": st.st_size}
        elif omitido:
            # el panel lo considera presente pero no se subió en esta corrida:
            # no se guarda estado, así la próxima corrida lo reintenta
            res["omitidos"] += 1
        else:
            res["errores"].append(f"{rel}: {msg}")
            estado_ws[remoto] = {"sha": sha, "size": st.st_size, "intentos": intentos_previos + 1}

    # huérfanos: en el servidor y sin equivalente local
    locales_remotos = {mgr._remote_name(rel) for rel in locales}
    huerfanos = [b for b in remotos
                 if not any(coincide_remoto(b, n) for n in locales_remotos)]
    res["huerfanos"] = sorted(huerfanos)

    # borrado de huérfanos (solo con borrar_huerfanos=True en sync_bot.json o
    # --borrar-huerfanos; el borrado usa el docpath completo como en app.py)
    if res["huerfanos"] and bot_cfg.get("borrar_huerfanos"):
        if dry:
            log.info("[dry-run] Se borrarían %d huérfanos de '%s': %s",
                     len(res["huerfanos"]), nombre, res["huerfanos"])
        else:
            docpaths = [doc_names[b] for b in res["huerfanos"]
                        if b in doc_names and doc_names[b]]
            log.info("Borrando %d huérfanos de '%s'", len(docpaths), nombre)
            ok, cnt, errs = mgr.delete_documents(docpaths)
            res["borrados"] = cnt
            if not ok:
                res["errores"].append(f"borrado de huérfanos: {errs[:3]}")

    if not dry:
        subido_algo = res["subidos"] or res["actualizados"]
        res["embeddings"] = mgr._update_embeddings(nombre) if subido_algo else False

    estado[slug] = estado_ws
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carpetas", help="lista separada por comas; por defecto las de sync_bot.json")
    ap.add_argument("--dry-run", action="store_true", help="solo reporta lo que haría")
    ap.add_argument("--sin-telegram", action="store_true")
    ap.add_argument("--sin-esperar-locks", action="store_true")
    ap.add_argument("--sin-actualizar", action="store_true", help="no reemplazar archivos cambiados")
    ap.add_argument("--max-subidas", type=int, default=0, help="máximo de subidas en esta corrida (0 = sin límite)")
    ap.add_argument("--borrar-huerfanos", action="store_true",
                    help="borrar del workspace los documentos sin equivalente local "
                         "(ignora sync_bot.json; p.ej. tras una corrida que reorganizó carpetas)")
    args = ap.parse_args()

    bot_cfg = cargar_bot_config()
    if args.sin_actualizar:
        bot_cfg["actualizar_cambiados"] = False
    if args.borrar_huerfanos:
        bot_cfg["borrar_huerfanos"] = True

    LOGS.mkdir(exist_ok=True)
    log_p = LOGS / f"sync_{datetime.datetime.now():%Y%m%d_%H%M}.log"
    # app.py ya hizo basicConfig (infohub.log + stdout); se añade el log propio
    # del bot sin quitar los suyos, así el archivo captura también los mensajes
    # de la clase InfoHubFileManager.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.getLogger().addHandler(logging.FileHandler(log_p, encoding="utf8"))

    lock = (LOGS / "sync_bot.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Ya hay una sincronización en curso; no se repite.")
        return 0

    inicio = datetime.datetime.now()
    print(f"Sincronización InfoHub {inicio:%Y-%m-%d %H:%M} — log: {log_p.name}")

    if not args.sin_esperar_locks:
        esperado = esperar_locks(bot_cfg["esperar_locks"], bot_cfg["espera_max_min"])
        if esperado > 60:
            print(f"Espera por los bots de normativa: {esperado/60:.1f} min")

    conf = ConfigManager()
    mgr = InfoHubFileManager(conf)
    if not mgr.api_key:
        print("Error: falta la API key de InfoHub (config.json o .env)")
        return 2
    resolver = WorkspaceResolver(mgr.base_url, mgr.api_key, aliases=bot_cfg.get("alias_workspaces"))

    root = pathlib.Path(bot_cfg["root"])
    if not root.is_dir():
        print(f"Error: no existe la carpeta raíz {root}")
        return 2

    if args.carpetas:
        nombres = [c.strip() for c in args.carpetas.split(",") if c.strip()]
    elif bot_cfg["carpetas"]:
        nombres = list(bot_cfg["carpetas"])
    else:
        nombres = sorted(d.name for d in root.iterdir() if d.is_dir())

    estado_p = BASE / bot_cfg["estado"]
    try:
        estado = json.loads(estado_p.read_text(encoding="utf8"))
    except (FileNotFoundError, ValueError):
        estado = {}

    restantes = [args.max_subidas or 10 ** 9]
    resultados, errores = [], 0
    for nombre in nombres:
        carpeta = root / nombre
        if not carpeta.is_dir():
            log.warning("Se omite '%s': no existe la carpeta", nombre)
            continue
        log.info("=== %s ===", nombre)
        t0 = time.time()
        try:
            r = sincronizar_carpeta(mgr, resolver, carpeta, bot_cfg, estado, args.dry_run,
                                    args.max_subidas, restantes)
        except Exception as e:
            # una caída de red no debe desincronizar el resolver: recarga el
            # índice de workspaces del servidor para la siguiente carpeta
            try:
                resolver.refresh()
            except Exception:
                pass
            r = {"carpeta": nombre, "errores": [f"excepción: {e}"], "locales": 0, "subidos": 0,
                 "actualizados": 0, "omitidos": 0, "huerfanos": [], "borrados": 0, "slug": None}
        r["seg"] = round(time.time() - t0)
        errores += len(r.get("errores", []))
        resultados.append(r)
        log.info("    slug=%s locales=%s subidos=%s actualizados=%s omitidos=%s huérfanos=%s errores=%s (%ss)",
                 r.get("slug"), r.get("locales"), r.get("subidos"), r.get("actualizados"),
                 r.get("omitidos"), len(r.get("huerfanos", [])), len(r.get("errores", [])), r["seg"])
        for e in r.get("errores", []):
            log.warning("    ERR %s: %s", nombre, e)
        for rel in r.get("ignorados", []):
            log.info("    IGN %s: extensión excluida", rel)
        for rel in r.get("fallidos", []):
            log.warning("    FAL %s: %s intentos fallidos con el mismo contenido", rel, bot_cfg.get("max_intentos", 3))

    if not args.dry_run:
        estado_p.parent.mkdir(parents=True, exist_ok=True)
        estado_p.write_text(json.dumps(estado, indent=1), encoding="utf8")

    total_seg = round((datetime.datetime.now() - inicio).total_seconds())
    lineas = [f"Sincronización InfoHub — {inicio:%Y-%m-%d %H:%M}"
              + (" (dry-run)" if args.dry_run else "")]
    for r in resultados:
        if r.get("protegido"):
            lineas.append(f"- {r['carpeta']} ({r['slug']}): protegido, omitido")
            continue
        det = f"{r['locales']} locales, {r['subidos']} subidos, {r['actualizados']} actualizados"
        if r.get("adoptados"):
            det += f", {r['adoptados']} ya existían"
        det += f", {r['omitidos']} iguales"
        if r.get("creado"):
            det += ", workspace creado"
        if r.get("ignorados"):
            det += f", {len(r['ignorados'])} ignorados por extensión"
        if r.get("fallidos"):
            det += f", {len(r['fallidos'])} fallidos persistentes"
        if r.get("huerfanos"):
            det += f", {len(r['huerfanos'])} huérfanos"
        if r.get("borrados"):
            det += f", {r['borrados']} borrados"
        if r.get("errores"):
            det += f", {len(r['errores'])} errores: {'; '.join(r['errores'][:3])}"
        lineas.append(f"- {r['carpeta']} ({r.get('slug') or 'sin workspace'}): {det} ({r['seg']//60} min)")
    lineas.append(f"Total: {total_seg//60} min. Log: logs/{log_p.name}")
    resumen = "\n".join(lineas)
    print(resumen)
    log.info("\n%s", resumen)

    if bot_cfg.get("telegram", True) and not args.sin_telegram and not args.dry_run:
        telegram(resumen)
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
