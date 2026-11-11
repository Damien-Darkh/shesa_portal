#!/usr/bin/env bash
set -Eeuo pipefail

echo "===== SHESA AUTHENTIK STATIC DIAGNOSTICS ====="

DC=(docker compose -f docker-compose.yml -f docker-compose.authentik.yml)

echo echo "===== 1. CONTAINER MOUNTS =====" "${DC[@]}" inspect authentik-server 2>/dev/null || true

echo echo "===== 2. STATIC FILES =====" "${DC[@]}" exec -T authentik-server sh -c ' find /web/static/shesa -maxdepth 3 -type f -ls '

echo echo "===== 3. STATIC CONFIGURATION =====" "${DC[@]}" exec -T authentik-server sh -c ' env | grep -Ei "STATIC|MEDIA|AUTHENTIK" | sort || true '

echo echo "===== 4. STATIC URL TESTS =====" for FILE in
css/login.css
js/login.js
images/logo.svg
images/logo_full.svg do echo echo "Testing: $FILE"

curl -sS -o /dev/null
-w "HTTP %{http_code}\n"
"http://127.0.0.1:9000/static/shesa/$FILE" || true done

echo echo "===== 5. DOCKER VOLUME CONFIGURATION =====" "${DC[@]}" config

echo echo "===== 6. AUTHENTIK LOGS =====" "${DC[@]}" logs --tail=30 authentik-server

echo echo "===== DIAGNOSTICS COMPLETE ====="
