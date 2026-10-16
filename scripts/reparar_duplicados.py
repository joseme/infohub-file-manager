#!/usr/bin/env python3
"""Repara documentos registrados varias veces por los reintentos de update-embeddings.

Causa: el proxy devolvía 504, `_update_embeddings` reintentaba con la lista completa
y el servidor volvía a registrar los mismos documentos (mismo docpath, docId nuevo).
Ya está corregido en app.py (cada intento recalcula pendientes), este script limpia
lo que quedó duplicado.

La API solo borra por NOMBRE (`DELETE /api/v1/system/remove-documents` con `names`),
y las copias comparten nombre: al borrar el nombre se van todas. Por eso, cuando hay
duplicados, hay que volver a subir una copia (`--re-subir` lanza sync_bot.py por
carpeta; el bot detecta que falta en el servidor y la sube una sola vez).

    ./venv/bin/python scripts/reparar_duplicados.py                    # solo informa
    ./venv/bin/python scripts/reparar_duplicados.py --aplicar          # borra duplicados
    ./venv/bin/python scripts/reparar_duplicados.py --aplicar --re-subir
"""

import argparse
import collections
import pathlib
import subprocess
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from config_manager import ConfigManager          # noqa: E402
from app import InfoHubFileManager                # noqa: E402

CARPETAS = ["Tributación CR", "Legislación Laboral CR", "Legislación Seguros CR",
            "odoo", "blawd", "zoho-tickets"]
LOTE = 25  # nombres por llamada de borrado (el proxy se cae con lotes grandes)


def analizar(mgr: InfoHubFileManager, carpeta: str) -> dict:
    """Cuenta entradas, docpaths repetidos y nombres a borrar para una carpeta."""
    docs = mgr.get_workspace_documents(carpeta)
    raw = [d for d in docs.get("raw_docs", []) if isinstance(d, dict)]
    por_path = collections.Counter(d.get("docpath") for d in raw if d.get("docpath"))
    dups = {p: n for p, n in por_path.items() if n > 1}
    nombres = sorted({p.split("/")[-1] for p in dups if p})
    return {"carpeta": carpeta, "entradas": len(raw), "docpaths": len(por_path),
            "duplicados": len(dups), "nombres": nombres}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carpetas", help="carpetas separadas por comas (por defecto todas)")
    ap.add_argument("--aplicar", action="store_true", help="borrar los nombres duplicados")
    ap.add_argument("--re-subir", action="store_true", help="tras borrar, correr sync_bot.py por carpeta")
    ap.add_argument("--sin-telegram", action="store_true", help="pasar --sin-telegram a sync_bot")
    args = ap.parse_args()

    conf = ConfigManager()
    mgr = InfoHubFileManager(conf)
    carpetas = [c.strip() for c in args.carpetas.split(",")] if args.carpetas else CARPETAS

    tocadas, total_dups = [], 0
    for carpeta in carpetas:
        info = analizar(mgr, carpeta)
        print(f"== {carpeta}: {info['entradas']} entradas, {info['docpaths']} docpaths, "
              f"{info['duplicados']} con copias repetidas")
        if not info["duplicados"]:
            continue
        total_dups += info["duplicados"]
        print(f"   ejemplos: {[n[:60] for n in info['nombres'][:3]]}")
        if not args.aplicar:
            continue

        borrados, errores = 0, []
        t0 = time.time()
        for i in range(0, len(info["nombres"]), LOTE):
            lote = info["nombres"][i:i + LOTE]
            ok, cnt, errs = mgr.delete_documents(lote)
            if ok:
                borrados += cnt
            else:
                errores.extend(errs[:1])
            if (i // LOTE) % 10 == 0:
                print(f"   borrados {borrados}/{len(info['nombres'])} ({round(time.time() - t0)}s)", flush=True)
        print(f"   borrados {borrados} nombres en {round(time.time() - t0)}s"
              + (f", {len(errores)} errores: {errores[:1]}" if errores else ""))

        despues = analizar(mgr, carpeta)
        print(f"   después: {despues['entradas']} entradas, {despues['duplicados']} duplicados")
        tocadas.append(carpeta)

    print(f"\nResumen: {total_dups} docpaths duplicados en {len(carpetas)} carpetas revisadas"
          + (f"; aplicado en: {', '.join(tocadas)}" if tocadas else " (sin --aplicar no se borró nada)"))

    if args.re_subir and tocadas:
        for carpeta in tocadas:
            cmd = [str(BASE / "venv/bin/python"), "sync_bot.py", "--carpetas", carpeta,
                   "--sin-esperar-locks"]
            if args.sin_telegram:
                cmd.append("--sin-telegram")
            print(f"\n### re-subiendo '{carpeta}' — los documentos borrados se suben una sola vez")
            subprocess.run(cmd, cwd=BASE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
