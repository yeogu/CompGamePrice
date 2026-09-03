#!/usr/bin/env bash
set -euo pipefail

api_binary="$1"
tracker_binary="$2"
curl_binary="$3"
api_port=19082
api_base="http://127.0.0.1:${api_port}"
project_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
test_root="$(mktemp -d)"
database="${test_root}/user-flow.db"
test_data="${test_root}/data"
primary_cookies="${test_root}/primary.cookies"
other_cookies="${test_root}/other.cookies"
body="${test_root}/response.json"
api_pid=""
rule_id=""

cleanup() {
    if [[ -n "${api_pid}" ]]; then
        kill "${api_pid}" 2>/dev/null || true
    fi
    rm -rf "${test_root}"
}
trap cleanup EXIT

status_for() {
    "${curl_binary}" -sS -o "${body}" -w '%{http_code}' "$@"
}

expect_status() {
    local expected="$1"
    shift
    local actual
    actual="$(status_for "$@")"
    if [[ "${actual}" != "${expected}" ]]; then
        echo "Expected HTTP ${expected}, received ${actual}" >&2
        cat "${body}" >&2
        return 1
    fi
}

notification_count() {
    {
        grep -o '"id":[0-9][0-9]*' "${body}" || true
    } | wc -l | tr -d ' '
}

prepare_fixture_and_api() {
    mkdir -p "${test_data}"
    cp "${project_directory}/data/"* "${test_data}/"
    GAME_PRICE_DATABASE_PATH="${database}" "${tracker_binary}" collect \
        --data-dir "${test_data}" Hades >/dev/null
    GAME_PRICE_DATABASE_PATH="${database}" GAME_PRICE_API_PORT="${api_port}" \
        WEB_APP_URL="http://127.0.0.1:5173" "${api_binary}" \
        >"${test_root}/api.log" 2>&1 &
    api_pid=$!
    for _ in {1..30}; do
        if "${curl_binary}" -fsS "${api_base}/health" >/dev/null 2>&1; then
            return
        fi
        sleep 0.1
    done
    echo "API did not become healthy" >&2
    cat "${test_root}/api.log" >&2
    return 1
}

verify_public_game_journey() {
    "${curl_binary}" -fsS "${api_base}/api/games?query=Hades" -o "${body}"
    grep -q '"id":"hades"' "${body}"
    grep -q '"title":"Hades"' "${body}"
    grep -q '"Nintendo Switch 2"' "${body}"

    "${curl_binary}" -fsS "${api_base}/api/games?query=no-such-game" -o "${body}"
    grep -q '"games":\[\]' "${body}"

    "${curl_binary}" -fsS \
        "${api_base}/api/games/hades/prices?platform=Nintendo%20Switch%202" \
        -o "${body}"
    grep -q '"id":"hades"' "${body}"
    grep -q '"store":"Nintendo eShop"' "${body}"
    grep -q '"minorAmount":28600' "${body}"
    grep -q '"offerType":"BaseGame"' "${body}"
    grep -q '"edition":"Standard"' "${body}"
    ! grep -q '"store":"Steam"' "${body}"

    "${curl_binary}" -fsS \
        "${api_base}/api/games/hades/price-history?platform=Nintendo%20Switch%202" \
        -o "${body}"
    grep -q '"store":"Nintendo eShop"' "${body}"
    grep -q '"observations":\[' "${body}"
    grep -q '"minorAmount":28600' "${body}"

    expect_status 404 "${api_base}/api/games/missing-game/prices"
}

verify_authentication_and_validation() {
    expect_status 401 \
        -H 'Content-Type: application/json' \
        -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":26000}' \
        "${api_base}/api/alert-rules"

    expect_status 201 \
        -c "${primary_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"email":"flow@example.com","password":"flow-password-123"}' \
        "${api_base}/api/auth/register"
    grep -q 'game_price_session' "${primary_cookies}"

    expect_status 200 \
        -b "${primary_cookies}" \
        -c "${primary_cookies}" \
        -X POST \
        "${api_base}/api/auth/logout"
    expect_status 401 -b "${primary_cookies}" "${api_base}/api/auth/me"

    expect_status 200 \
        -b "${primary_cookies}" \
        -c "${primary_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"email":"flow@example.com","password":"flow-password-123"}' \
        "${api_base}/api/auth/login"
    expect_status 200 -b "${primary_cookies}" "${api_base}/api/auth/me"
    grep -q '"email":"flow@example.com"' "${body}"

    expect_status 400 \
        -b "${primary_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":0}' \
        "${api_base}/api/alert-rules"
    expect_status 400 \
        -b "${primary_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":26000,"platform":"PlayStation 5"}' \
        "${api_base}/api/alert-rules"
    expect_status 404 \
        -b "${primary_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"gameId":"missing-game","type":"BelowTargetPrice","targetPriceMinor":26000}' \
        "${api_base}/api/alert-rules"
}

create_and_verify_persisted_alert() {
    expect_status 201 \
        -b "${primary_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":26000,"platform":"Nintendo Switch 2"}' \
        "${api_base}/api/alert-rules"
    rule_id="$(sed -E 's/.*"id":([0-9]+).*/\1/' "${body}")"
    [[ "${rule_id}" =~ ^[0-9]+$ ]]

    "${curl_binary}" -fsS -b "${primary_cookies}" \
        "${api_base}/api/alert-rules" -o "${body}"
    grep -q '"gameTitle":"Hades"' "${body}"
    grep -q '"platform":"Nintendo Switch 2"' "${body}"
    grep -q '"targetPriceMinor":26000' "${body}"

    expect_status 409 \
        -b "${primary_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":26000,"platform":"Nintendo Switch 2"}' \
        "${api_base}/api/alert-rules"

    "${curl_binary}" -fsS -b "${primary_cookies}" \
        "${api_base}/api/notifications" -o "${body}"
    [[ "$(notification_count)" == "0" ]]
}

verify_user_isolation() {
    expect_status 201 \
        -c "${other_cookies}" \
        -H 'Content-Type: application/json' \
        -d '{"email":"other@example.com","password":"other-password-123"}' \
        "${api_base}/api/auth/register"
    "${curl_binary}" -fsS -b "${other_cookies}" \
        "${api_base}/api/alert-rules" -o "${body}"
    grep -q '"rules":\[\]' "${body}"
    expect_status 404 \
        -b "${other_cookies}" \
        -X DELETE \
        "${api_base}/api/alert-rules/${rule_id}"
}

cross_target_and_verify_notification() {
    sed -i.bak \
        's/70010000033128,hades,28600,28600,0/70010000033128,hades,28600,25000,13/' \
        "${test_data}/nintendo_eshop_products.csv"
    GAME_PRICE_DATABASE_PATH="${database}" "${tracker_binary}" collect \
        --data-dir "${test_data}" Hades >/dev/null

    "${curl_binary}" -fsS -b "${primary_cookies}" \
        "${api_base}/api/notifications" -o "${body}"
    [[ "$(notification_count)" == "1" ]]
    grep -q '"store":"Nintendo eShop"' "${body}"
    grep -q '"productId":"70010000033128"' "${body}"
    grep -q '"minorAmount":25000' "${body}"
    ! grep -q '"store":"Steam"' "${body}"
    ! grep -q '"store":"Epic Games Store"' "${body}"

    GAME_PRICE_DATABASE_PATH="${database}" "${tracker_binary}" collect \
        --data-dir "${test_data}" Hades >/dev/null
    "${curl_binary}" -fsS -b "${primary_cookies}" \
        "${api_base}/api/notifications" -o "${body}"
    [[ "$(notification_count)" == "1" ]]

    "${curl_binary}" -fsS -b "${other_cookies}" \
        "${api_base}/api/notifications" -o "${body}"
    [[ "$(notification_count)" == "0" ]]
}

verify_logout_revokes_session() {
    expect_status 200 \
        -b "${primary_cookies}" \
        -c "${primary_cookies}" \
        -X POST \
        "${api_base}/api/auth/logout"
    expect_status 401 -b "${primary_cookies}" "${api_base}/api/alert-rules"
    expect_status 401 -b "${primary_cookies}" "${api_base}/api/notifications"
}

prepare_fixture_and_api
verify_public_game_journey
verify_authentication_and_validation
create_and_verify_persisted_alert
verify_user_isolation
cross_target_and_verify_notification
verify_logout_revokes_session
