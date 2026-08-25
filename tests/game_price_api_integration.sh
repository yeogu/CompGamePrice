#!/usr/bin/env bash
set -euo pipefail

api_binary="$1"
tracker_binary="$2"
curl_binary="$3"
api_port=19081
api_base="http://127.0.0.1:${api_port}"
response_body="/tmp/game_price_api_response_$$.json"

cleanup() {
    if [[ -n "${api_pid:-}" ]]; then kill "${api_pid}" 2>/dev/null || true; fi
    rm -f "${response_body}"
}
trap cleanup EXIT

"${tracker_binary}" collect "Stardew Valley" >/dev/null
GAME_PRICE_API_PORT="${api_port}" "${api_binary}" >/dev/null 2>&1 &
api_pid=$!

for _ in {1..30}; do
    if "${curl_binary}" -fsS "${api_base}/health" >/dev/null 2>&1; then break; fi
    sleep 0.1
done

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/stardew-valley/price-history")
[[ "${status}" == "200" ]]
grep -q '"minorAmount"' "${response_body}"
grep -q '"observedAt"' "${response_body}"
grep -q '"store":"Steam"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/stardew-valley/price-history?since=invalid")
[[ "${status}" == "400" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/missing/price-history")
[[ "${status}" == "404" ]]
