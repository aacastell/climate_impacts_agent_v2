#!/usr/bin/env bash
# Builds the real static output and serves exactly that — bundled,
# minified, tree-shaken — the closest local stand-in for what CloudFront
# will actually serve. No hot reload: rebuild and rerun after changes.
# For active iteration while writing code, use dev.sh instead.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/build-frontend.sh"

source "$HOME/.nvm/nvm.sh"
cd "$ROOT/frontend"
nvm use
npm run preview
