#!/usr/bin/env bash
# Builds the frontend's static output (frontend/dist/). Shared by
# local.sh and deploy.sh — one place this step is defined.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/frontend"

# nvm exists on a local dev machine (and this pins the exact version via
# .nvmrc) but not in an environment like CodeBuild, which selects Node
# through its own buildspec runtime-versions mechanism instead. Only use
# nvm when it's actually there; otherwise trust whatever node/npm is
# already on PATH.
if [ -s "$HOME/.nvm/nvm.sh" ]; then
  source "$HOME/.nvm/nvm.sh"
  nvm use
fi

if [ ! -d node_modules ]; then
  npm install
fi

echo "==> Building frontend"
npm run build
