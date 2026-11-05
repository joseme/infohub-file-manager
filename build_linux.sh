#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
# Mismas versiones fijas que el Dockerfile: sin flet-web el ejecutable no arranca
# y flet-web 0.85 no funciona con FastAPI 0.156 o posterior.
pip install -r requirements.txt flet-web==0.85.2 fastapi==0.136.3 pyinstaller
pyinstaller build.spec --clean
chmod +x dist/infohub-file-manager
# El ejecutable sirve assets/ desde su propia carpeta (BASE_DIR en config_manager.py)
rm -rf dist/assets
cp -r assets dist/assets
echo ""
echo "Build OK: dist/infohub-file-manager"
echo "Run with: ./dist/infohub-file-manager"
