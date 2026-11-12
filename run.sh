#!/usr/bin/env bash
# Build everything and start the Trackflow demo on http://localhost:3000
set -e
cd "$(dirname "$0")"

echo "==> building the C++ engine"
make -C engine -j

echo "==> installing + building the dashboard"
(cd web && npm install --no-audit --no-fund && npm run build)

echo "==> installing the bridge"
(cd server && npm install --no-audit --no-fund)

echo "==> starting on http://localhost:3000"
cd server && PORT=${PORT:-3000} node index.js
