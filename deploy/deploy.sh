#!/usr/bin/env bash
# Deploy InfoHub File Manager to the remote server (servercheap = 65.75.202.27).
# Usage: ./deploy/deploy.sh
set -euo pipefail

REMOTE_HOST="deploy@65.75.202.27"
REMOTE_DIR="/home/deploy/infohub-file-manager"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Copying project to ${REMOTE_HOST}:${REMOTE_DIR}"
ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'"

rsync -az --delete \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude '.codebase/' \
  --exclude '.codegraph' \
  --exclude '.omo/' \
  --exclude '.opencode/' \
  --exclude '.planning/' \
  --exclude '.playwright-mcp/' \
  --exclude '.pytest_cache/' \
  --exclude 'tests/' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude '*.log' \
  --exclude 'app (copia 1).py' \
  --exclude 'config.json' \
  --exclude 'data/' \
  "$LOCAL_DIR"/ "$REMOTE_HOST:$REMOTE_DIR/"

echo "==> Ensuring persistent files exist on the server (won't overwrite existing config)"
ssh "$REMOTE_HOST" "
  set -e
  cd '$REMOTE_DIR'
  mkdir -p data
  [ -f config.json ] || cp deploy/config.blank.json config.json
  touch infohub.log
"

echo "==> Building and starting the container"
ssh "$REMOTE_HOST" "cd '$REMOTE_DIR' && docker compose up -d --build"

echo "==> Done. Check status with: ssh $REMOTE_HOST 'cd $REMOTE_DIR && docker compose ps'"
