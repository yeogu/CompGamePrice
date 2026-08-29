#!/usr/bin/env bash
set -euo pipefail

api_binary="$1"
tracker_binary="$2"
curl_binary="$3"
api_port=19083
api_base="http://127.0.0.1:${api_port}"
test_root="$(mktemp -d)"
test_database="${test_root}/data-reliability.db"
test_data="${test_root}/data"
response_body="${test_root}/response.json"
project_directory="$(cd "$(dirname "${tracker_binary}")/.." && pwd)"
api_pid=""

cleanup() {
    if [[ -n "${api_pid}" ]]; then
        kill "${api_pid}" 2>/dev/null || true
    fi
    rm -rf "${test_root}"
}
trap cleanup EXIT

mkdir -p "${test_data}"
cp "${project_directory}/data/"* "${test_data}/"
cp "${project_directory}/tests/fixtures/epic_games_products_mixed.txt" \
    "${test_data}/epic_games_products.txt"

GAME_PRICE_DATABASE_PATH="${test_database}" \
    "${tracker_binary}" collect --data-dir "${test_data}" Hades >/dev/null
GAME_PRICE_DATABASE_PATH="${test_database}" \
    "${tracker_binary}" collect --data-dir "${test_data}" Hades >/dev/null

GAME_PRICE_DATABASE_PATH="${test_database}" \
GAME_PRICE_API_PORT="${api_port}" \
    "${api_binary}" >"${test_root}/api.log" 2>&1 &
api_pid=$!

for _ in {1..30}; do
    if "${curl_binary}" -fsS "${api_base}/health" >/dev/null; then
        break
    fi
    sleep 0.1
done

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/hades/prices")
[[ "${status}" == "200" ]]
grep -q '"cheapest".*"store":"Epic Games Store"' "${response_body}"
grep -q '"freshness":"Fresh"' "${response_body}"
grep -q '"currency":"KRW"' "${response_body}"
if grep -q '"productId":"broken"' "${response_body}"; then
    echo "Rejected Epic product leaked into the price API" >&2
    exit 1
fi

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/hades/price-history")
[[ "${status}" == "200" ]]
observation_count=$(grep -o '"observedAt"' "${response_body}" | wc -l | tr -d ' ')
[[ "${observation_count}" == "3" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/collection-runs?limit=10")
[[ "${status}" == "200" ]]
grep -q '"productsRejected":1' "${response_body}"
grep -q '"productsFound":1' "${response_body}"

