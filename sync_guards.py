"""Guardas compartidas contra borrados masivos de documentos en InfoHub.

Las usan sync_bot.py (borrado de huérfanos programado) y app.py (carga completa
desde el panel). Un documento del workspace es «huérfano» cuando no tiene
equivalente en la carpeta local; si la carpeta aparece vacía o a medias (un
montaje SMB caído, un disco desconectado, una sincronización a medias), todo el
workspace parecería huérfano. Estas funciones deciden cuándo NO borrar.

Tres guardas, todas puras (sin red) y testeables:

1. evaluar_borrado(): bloquea si la carpeta local está vacía, o si el borrado
   se llevaría más de `umbral_pct` % de los documentos del workspace (con un
   mínimo absoluto, para que los workspaces pequeños se sigan limpiando).
2. montaje_caido(): bloquea si la carpeta está declarada como punto de montaje
   (`montajes_requeridos`) y no está montada.
3. nombres_externos(): documentos subidos por fuentes externas (SharePoint,
   Zoho...) según logs/estado_fuentes.json; nunca cuentan como huérfanos
   porque no tienen copia local por diseño.
"""

import json
import logging
import os
import pathlib
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

BASE = pathlib.Path(__file__).resolve().parent
ESTADO_FUENTES = BASE / "logs" / "estado_fuentes.json"

UMBRAL_PCT_DEFECTO = 50
MINIMO_DEFECTO = 10


def evaluar_borrado(locales: int, remotos: int, huerfanos: int,
                    umbral_pct: float = UMBRAL_PCT_DEFECTO,
                    minimo: int = MINIMO_DEFECTO) -> Optional[str]:
    """Devuelve el motivo para bloquear el borrado de huérfanos, o None si se permite.

    - locales: archivos locales de la carpeta (tras filtros).
    - remotos: documentos del workspace en el servidor.
    - huerfanos: cuántos de ellos se borrarían.
    """
    if huerfanos <= 0:
        return None
    if locales <= 0:
        return (f"la carpeta local está vacía y se borrarían {huerfanos} documentos "
                f"(¿montaje caído o disco desconectado?)")
    if remotos > 0 and huerfanos > minimo:
        pct = huerfanos * 100 / remotos
        if pct > umbral_pct:
            return (f"se borrarían {huerfanos} de {remotos} documentos ({pct:.0f} %), "
                    f"más del umbral de {umbral_pct:g} %")
    return None


def montaje_caido(carpeta, montajes: Iterable) -> bool:
    """True si `carpeta` es (o está dentro de) un montaje requerido que no está montado."""
    try:
        carpeta = pathlib.Path(carpeta).resolve()
    except OSError:
        return True
    for m in montajes or []:
        if not m:
            continue
        punto = pathlib.Path(os.path.expanduser(str(m))).resolve()
        if carpeta == punto or punto in carpeta.parents:
            if not os.path.ismount(punto):
                return True
    return False


def raiz_accesible(raiz) -> Optional[str]:
    """Motivo si la carpeta raíz no se puede listar; None si está bien."""
    raiz = pathlib.Path(raiz)
    try:
        if not raiz.is_dir():
            return f"no existe la carpeta raíz {raiz}"
        os.listdir(raiz)
    except OSError as e:
        return f"la carpeta raíz {raiz} no es accesible ({e})"
    return None


def cargar_estado_fuentes(ruta=None) -> dict:
    """Lee logs/estado_fuentes.json; {} si no existe o está corrupto."""
    ruta = pathlib.Path(ruta) if ruta else ESTADO_FUENTES
    try:
        datos = json.loads(ruta.read_text(encoding="utf8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("No se pudo leer %s (%s): se asume sin fuentes externas", ruta, e)
        return {}
    return datos if isinstance(datos, dict) else {}


def nombres_externos(slug: str, estado_fuentes: dict) -> set:
    """Nombres remotos que las fuentes externas subieron al workspace `slug`.

    Formato de estado_fuentes (ver docs/plan_trabajo_maestro.md, F3.3):
    {"<fuente>": {"<id>": {"slug": ..., "remote_name": ...}}, "_meta": {...}}
    """
    nombres = set()
    for fuente, entradas in (estado_fuentes or {}).items():
        if fuente.startswith("_") or not isinstance(entradas, dict):
            continue
        for e in entradas.values():
            if isinstance(e, dict) and e.get("slug") == slug and e.get("remote_name"):
                nombres.add(e["remote_name"])
    return nombres


def quitar_externos(huerfanos: Iterable, externos: set,
                    coincide: Callable[[str, str], bool]) -> list:
    """Filtra de `huerfanos` (bases del servidor) los que pertenecen a fuentes externas."""
    if not externos:
        return list(huerfanos)
    return [b for b in huerfanos if not any(coincide(b, n) for n in externos)]
