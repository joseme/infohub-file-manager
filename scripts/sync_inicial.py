#!/usr/bin/env python3
"""Carga inicial de las carpetas de ~/Documentos/Infohub en los workspaces de InfoHub.

Corre sync_bot.py carpeta por carpeta (de la más pequeña a la más grande) para que
cada corrida deje su propio log y su resumen de Telegram, y para que un fallo en una
carpeta no arrastre a las demás.

Pensado para lanzarse a mano UNA vez: el cron semanal (domingos 06:30) ya mantiene
la carga incremental.

    ./venv/bin/python scripts/sync_inicial.py
    ./venv/bin/python scripts/sync_inicial.py --orden "Tributación CR,odoo"
    ./venv/bin/python scripts/sync_inicial.py --sin-telegram
"""

import argparse
import pathlib
import subprocess
import sys
import time

BASE = pathlib.Path(__file__).resolve().parent.parent
ORDEN = ["Legislación Seguros CR", "Legislación Laboral CR", "Tributación CR", "odoo"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orden", default=",".join(ORDEN),
                    help="carpetas separadas por comas, en el orden de ejecución")
    ap.add_argument("--sin-telegram", action="store_true")
    args = ap.parse_args()

    carpetas = [c.strip() for c in args.orden.split(",") if c.strip()]
    fallidas = []
    for carpeta in carpetas:
        cmd = [str(BASE / "venv/bin/python"), "sync_bot.py", "--carpetas", carpeta,
               "--sin-esperar-locks"]
        if args.sin_telegram:
            cmd.append("--sin-telegram")
        t0 = time.time()
        print(f"### {carpeta} — inicio {time.strftime('%H:%M:%S')}", flush=True)
        r = subprocess.run(cmd, cwd=BASE)
        print(f"### {carpeta} — exit={r.returncode} en {round(time.time() - t0)}s", flush=True)
        if r.returncode:
            fallidas.append(carpeta)

    print(f"### fin: {len(carpetas) - len(fallidas)}/{len(carpetas)} carpetas sin error"
          + (f"; con error: {', '.join(fallidas)}" if fallidas else ""), flush=True)
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
