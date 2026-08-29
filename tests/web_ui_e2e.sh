#!/usr/bin/env bash
set -euo pipefail

project_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tracker_binary="${1:-${project_directory}/build/game_price_tracker}"
api_binary="${2:-${project_directory}/build/game_price_api}"
api_port=19084
web_port=15173
test_root="$(mktemp -d)"
database="${test_root}/web-ui-e2e.db"
api_pid=""
web_pid=""

cleanup() {
    if [[ -n "${web_pid}" ]]; then
        kill "${web_pid}" 2>/dev/null || true
    fi
    if [[ -n "${api_pid}" ]]; then
        kill "${api_pid}" 2>/dev/null || true
    fi
    rm -rf "${test_root}"
}
trap cleanup EXIT

GAME_PRICE_DATABASE_PATH="${database}" "${tracker_binary}" collect \
    --data-dir "${project_directory}/data" Hades >/dev/null

GAME_PRICE_DATABASE_PATH="${database}" GAME_PRICE_API_PORT="${api_port}" \
    WEB_APP_URL="http://127.0.0.1:${web_port}" "${api_binary}" \
    >"${test_root}/api.log" 2>&1 &
api_pid=$!

VITE_API_URL="http://127.0.0.1:${api_port}" \
    "${project_directory}/web/node_modules/.bin/vite" \
    --host 127.0.0.1 --port "${web_port}" \
    >"${test_root}/web.log" 2>&1 &
web_pid=$!

for _ in {1..50}; do
    if curl -fsS "http://127.0.0.1:${api_port}/health" >/dev/null 2>&1 && \
        curl -fsS "http://127.0.0.1:${web_port}" >/dev/null 2>&1; then
        WEB_E2E_BASE_URL="http://127.0.0.1:${web_port}" \
            "${project_directory}/web/node_modules/.bin/playwright" test \
            --config "${project_directory}/web/playwright.config.ts"
        exit
    fi
    sleep 0.1
done

echo "UI E2E servers did not become ready" >&2
cat "${test_root}/api.log" >&2
cat "${test_root}/web.log" >&2
exit 1
