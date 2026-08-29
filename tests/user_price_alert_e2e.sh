#!/usr/bin/env bash
set -euo pipefail

api_binary="$1"
tracker_binary="$2"
curl_binary="$3"
api_port=19082
api_base="http://127.0.0.1:${api_port}"
database="/tmp/game_price_user_flow_$$.db"
cookies="/tmp/game_price_user_flow_$$.cookies"
body="/tmp/game_price_user_flow_$$.json"
project_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

cleanup() {
    if [[ -n "${api_pid:-}" ]]; then kill "${api_pid}" 2>/dev/null || true; fi
    rm -f "${database}" "${database}-shm" "${database}-wal" "${cookies}" "${body}"
}
trap cleanup EXIT

GAME_PRICE_DATABASE_PATH="${database}" "${tracker_binary}" collect \
    --data-dir "${project_directory}/data" Hades >/dev/null
GAME_PRICE_DATABASE_PATH="${database}" GAME_PRICE_API_PORT="${api_port}" \
    WEB_APP_URL="http://127.0.0.1:5173" "${api_binary}" >/dev/null 2>&1 &
api_pid=$!
for _ in {1..30}; do
    if "${curl_binary}" -fsS "${api_base}/health" >/dev/null 2>&1; then break; fi
    sleep 0.1
done

# 1. Search for the game.
"${curl_binary}" -fsS "${api_base}/api/games?query=Hades" -o "${body}"
grep -q '"id":"hades"' "${body}"

# 2. Inspect Nintendo Switch 2 prices and matching history.
"${curl_binary}" -fsS "${api_base}/api/games/hades/prices?platform=Nintendo%20Switch%202" -o "${body}"
grep -q '"store":"Nintendo eShop"' "${body}"
! grep -q '"store":"Steam"' "${body}"
"${curl_binary}" -fsS "${api_base}/api/games/hades/price-history?platform=Nintendo%20Switch%202" -o "${body}"
grep -q '"store":"Nintendo eShop"' "${body}"
! grep -q '"store":"Epic Games Store"' "${body}"

# 3. Register and keep the HttpOnly browser-style session cookie.
status=$("${curl_binary}" -sS -o "${body}" -w '%{http_code}' -c "${cookies}" \
    -H 'Content-Type: application/json' \
    -d '{"email":"flow@example.com","password":"flow-password-123"}' \
    "${api_base}/api/auth/register")
[[ "${status}" == "201" ]]
grep -q 'game_price_session' "${cookies}"

# 4. Create a platform-scoped target price alert.
status=$("${curl_binary}" -sS -o "${body}" -w '%{http_code}' -b "${cookies}" \
    -H 'Content-Type: application/json' \
    -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":30000,"platform":"Nintendo Switch 2"}' \
    "${api_base}/api/alert-rules")
[[ "${status}" == "201" ]]
"${curl_binary}" -fsS -b "${cookies}" "${api_base}/api/alert-rules" -o "${body}"
grep -q '"gameTitle":"Hades"' "${body}"
grep -q '"platform":"Nintendo Switch 2"' "${body}"

# 5. Collect again and verify only the matching platform creates an alert.
GAME_PRICE_DATABASE_PATH="${database}" "${tracker_binary}" collect \
    --data-dir "${project_directory}/data" Hades >/dev/null
"${curl_binary}" -fsS -b "${cookies}" "${api_base}/api/notifications" -o "${body}"
grep -q '"store":"Nintendo eShop"' "${body}"
! grep -q '"store":"Steam"' "${body}"
! grep -q '"store":"Epic Games Store"' "${body}"
notification_count=$(grep -o '"id":[0-9][0-9]*' "${body}" | wc -l | tr -d ' ')
[[ "${notification_count}" == "1" ]]
