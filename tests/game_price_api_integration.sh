#!/usr/bin/env bash
set -euo pipefail

api_binary="$1"
tracker_binary="$2"
curl_binary="$3"
api_port=19081
api_base="http://127.0.0.1:${api_port}"
response_body="/tmp/game_price_api_response_$$.json"
test_database="/tmp/game_price_api_test_$$.db"
project_directory=$(cd "$(dirname "${tracker_binary}")/.." && pwd)

cleanup() {
    if [[ -n "${api_pid:-}" ]]; then kill "${api_pid}" 2>/dev/null || true; fi
    rm -f "${response_body}" "${test_database}" "${test_database}-shm" "${test_database}-wal"
}
trap cleanup EXIT

GAME_PRICE_DATABASE_PATH="${test_database}" "${tracker_binary}" seed-demo >/dev/null
GAME_PRICE_DATABASE_PATH="${test_database}" "${tracker_binary}" collect \
    --data-dir "${project_directory}/data" Hades >/dev/null
GAME_PRICE_DATABASE_PATH="${test_database}" GAME_PRICE_API_PORT="${api_port}" \
    "${api_binary}" >/dev/null 2>&1 &
api_pid=$!

for _ in {1..30}; do
    if "${curl_binary}" -fsS "${api_base}/health" >/dev/null 2>&1; then break; fi
    sleep 0.1
done

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/stardew-valley/prices")
[[ "${status}" == "200" ]]
grep -q '"purchaseUrl":"https://store.steampowered.com/app/413150"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/stardew-valley/price-history")
[[ "${status}" == "200" ]]
grep -q '"minorAmount"' "${response_body}"
grep -q '"observedAt"' "${response_body}"
grep -q '"store":"Steam"' "${response_body}"
grep -q '"discountPercent":0' "${response_body}"
grep -q '"discountPercent":36' "${response_body}"
grep -q '"regularPrice"' "${response_body}"
[[ $(grep -o '"observedAt"' "${response_body}" | wc -l | tr -d ' ') == "13" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/stardew-valley/price-history?since=invalid")
[[ "${status}" == "400" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/missing/price-history")
[[ "${status}" == "404" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games")
[[ "${status}" == "200" ]]
grep -q '"id":"stardew-valley"' "${response_body}"
grep -q '"id":"terraria"' "${response_body}"
grep -q '"id":"hollow-knight"' "${response_body}"
grep -q '"id":"hades"' "${response_body}"
grep -q '"platforms":\["Windows","macOS","Linux"\]' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?query=terraria")
[[ "${status}" == "200" ]]
grep -q '"id":"terraria"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/terraria/prices")
[[ "${status}" == "200" ]]
grep -q '"title":"Terraria"' "${response_body}"
grep -q '"products":\[\]' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/hades/prices")
[[ "${status}" == "200" ]]
grep -q '"store":"Steam"' "${response_body}"
grep -q '"store":"Epic Games Store"' "${response_body}"
grep -q '"purchaseUrl":"https://store.epicgames.com/p/hades"' "${response_body}"
grep -q '"minorAmount":25000' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/collection-runs?limit=5")
[[ "${status}" == "200" ]]
grep -q '"store":"Epic Games Store"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/collection-runs?limit=invalid")
[[ "${status}" == "400" ]]
