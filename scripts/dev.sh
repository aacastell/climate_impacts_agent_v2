#!/usr/bin/env bash
# Fast local iteration loop: Vite serves unbundled source, transformed on
# demand, with hot module replacement. This is not what ships — it's a
# different code path than the build (no bundling, no minification, no
# tree-shaking), so it can't tell you the built artifact actually works.
# For that, use local.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

source "$HOME/.nvm/nvm.sh"
cd "$ROOT/frontend"
nvm use

if [ ! -d node_modules ]; then
  npm install
fi

echo "==> http://localhost:5173"
npm run dev
