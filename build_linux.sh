#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller build.spec --clean
chmod +x dist/infohub-file-manager
echo ""
echo "Build OK: dist/infohub-file-manager"
echo "Run with: ./dist/infohub-file-manager"
