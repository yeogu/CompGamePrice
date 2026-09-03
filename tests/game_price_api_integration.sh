#!/usr/bin/env bash
set -euo pipefail

api_binary="$1"
tracker_binary="$2"
curl_binary="$3"
api_port=19081
api_base="http://127.0.0.1:${api_port}"
response_body="/tmp/game_price_api_response_$$.json"
test_database="/tmp/game_price_api_test_$$.db"
test_catalog="/tmp/game_price_api_catalog_$$.json"
cookie_jar="/tmp/game_price_api_cookie_$$.txt"
project_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

cleanup() {
    if [[ -n "${api_pid:-}" ]]; then kill "${api_pid}" 2>/dev/null || true; fi
    rm -f "${response_body}" "${cookie_jar}" "${test_catalog}" "${test_database}" "${test_database}-shm" "${test_database}-wal"
}
trap cleanup EXIT

python3 - "${project_directory}/data/game_catalog.json" "${test_catalog}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    catalog = json.load(source)

catalog["games"].append({
    "id": "unpriced-nintendo-game",
    "title": "Unpriced Nintendo Game",
    "platforms": ["NintendoSwitch"],
    "genres": ["Test"],
    "tags": [],
    "aliases": [],
    "developers": ["Test"],
    "publishers": ["Test"],
    "products": [{
        "store": "NintendoEShop",
        "productId": "test-without-price",
        "productUrl": "https://example.invalid/unpriced-nintendo-game",
        "platforms": ["NintendoSwitch"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }],
})
with open(sys.argv[2], "w", encoding="utf-8") as output:
    json.dump(catalog, output)
PY

GAME_PRICE_DATABASE_PATH="${test_database}" "${tracker_binary}" seed-demo >/dev/null
GAME_PRICE_DATABASE_PATH="${test_database}" "${tracker_binary}" collect \
    --data-dir "${project_directory}/data" Hades >/dev/null
GAME_PRICE_DATABASE_PATH="${test_database}" GAME_PRICE_CATALOG_PATH="${test_catalog}" \
    GAME_PRICE_API_PORT="${api_port}" \
    CATALOG_ADMIN_ENABLED=true \
    GOOGLE_OAUTH_CLIENT_ID="google-test-id" GOOGLE_OAUTH_CLIENT_SECRET="google-test-secret" \
    KAKAO_OAUTH_CLIENT_ID="kakao-test-id" KAKAO_OAUTH_CLIENT_SECRET="kakao-test-secret" \
    NAVER_OAUTH_CLIENT_ID="naver-test-id" NAVER_OAUTH_CLIENT_SECRET="naver-test-secret" \
    "${api_binary}" >/dev/null 2>&1 &
api_pid=$!

for _ in {1..30}; do
    if "${curl_binary}" -fsS "${api_base}/health" >/dev/null 2>&1; then break; fi
    sleep 0.1
done

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -c "${cookie_jar}" \
    -H 'Content-Type: application/json' -d '{"email":"test@example.com","password":"test-password-123"}' \
    "${api_base}/api/auth/register")
[[ "${status}" == "201" ]]
auth_token=$(grep -o '"token":"[^"]*"' "${response_body}" | cut -d '"' -f 4)
[[ -n "${auth_token}" ]]
grep -q 'game_price_session' "${cookie_jar}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/auth/me")
[[ "${status}" == "200" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"email":"test@example.com"}' \
    "${api_base}/api/auth/password-reset/request")
[[ "${status}" == "202" ]]
grep -q 'If the account exists' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"email":"missing@example.com"}' \
    "${api_base}/api/auth/password-reset/request")
[[ "${status}" == "202" ]]
grep -q 'If the account exists' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"token":"invalid","password":"new-password-123"}' \
    "${api_base}/api/auth/password-reset/confirm")
[[ "${status}" == "400" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"gameId":"hades"}' \
    "${api_base}/api/favorites")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" -H 'Content-Type: application/json' \
    -d '{"gameId":"hades"}' \
    "${api_base}/api/favorites")
[[ "${status}" == "201" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/favorites")
[[ "${status}" == "200" ]]
grep -q '"id":"hades"' "${response_body}"
grep -q '"title":"Hades"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/account/preferences")
[[ "${status}" == "200" ]]
grep -q '"emailNotificationsEnabled":true' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" -H 'Content-Type: application/json' -X PATCH \
    -d '{"emailNotificationsEnabled":false,"region":"KR","currency":"KRW"}' \
    "${api_base}/api/account/preferences")
[[ "${status}" == "200" ]]
grep -q '"emailNotificationsEnabled":false' "${response_body}"

for _ in {1..5}; do
    status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        -d '{"email":"limited@example.com","password":"wrong-password"}' \
        "${api_base}/api/auth/login")
    [[ "${status}" == "401" ]]
done
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"email":"limited@example.com","password":"wrong-password"}' \
    "${api_base}/api/auth/login")
[[ "${status}" == "429" ]]

for provider in google kakao naver; do
    status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
        "${api_base}/api/oauth/${provider}/start")
    [[ "${status}" == "200" ]]
    grep -q '"authorizationUrl":"https://' "${response_body}"
    grep -q 'state=' "${response_body}"
done
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/oauth/google/start?link=true")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" \
    "${api_base}/api/oauth/google/start?link=true")
[[ "${status}" == "200" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/alert-rules")
[[ "${status}" == "401" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" -H 'Content-Type: application/json' \
    -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":30000,"platform":"Nintendo Switch 2"}' \
    "${api_base}/api/alert-rules")
[[ "${status}" == "201" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" -H 'Content-Type: application/json' \
    -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":30000,"platform":"Nintendo Switch 2"}' \
    "${api_base}/api/alert-rules")
[[ "${status}" == "409" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" -H 'Content-Type: application/json' \
    -d '{"gameId":"hades","type":"BelowTargetPrice","targetPriceMinor":0}' \
    "${api_base}/api/alert-rules")
[[ "${status}" == "400" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" "${api_base}/api/alert-rules")
[[ "${status}" == "200" ]]
grep -q '"gameTitle":"Hades"' "${response_body}"
grep -q '"platform":"Nintendo Switch 2"' "${response_body}"
GAME_PRICE_DATABASE_PATH="${test_database}" "${tracker_binary}" collect \
    --data-dir "${project_directory}/data" Hades >/dev/null
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" "${api_base}/api/notifications")
[[ "${status}" == "200" ]]
grep -q '"gameId":"hades"' "${response_body}"
grep -q '"store":"Nintendo eShop"' "${response_body}"
! grep -q '"store":"Epic Games Store"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" -X DELETE "${api_base}/api/alert-rules/999999")
[[ "${status}" == "404" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H "Authorization: Bearer ${auth_token}" -X PATCH "${api_base}/api/notifications/999999/read")
[[ "${status}" == "404" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/stardew-valley/prices")
[[ "${status}" == "200" ]]
grep -q '"purchaseUrl":"https://store.steampowered.com/app/413150"' "${response_body}"
grep -q '"freshness":"Fresh"' "${response_body}"
grep -q '"stale":false' "${response_body}"
grep -q '"lastCheckedAt"' "${response_body}"
grep -q '"lastSuccessfulCheckAt"' "${response_body}"

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
    "${api_base}/api/games?pageSize=100")
[[ "${status}" == "200" ]]
grep -q '"id":"stardew-valley"' "${response_body}"
grep -q '"id":"terraria"' "${response_body}"
grep -q '"id":"hollow-knight"' "${response_body}"
grep -q '"id":"hades"' "${response_body}"
grep -q '"platforms":\["Windows","macOS","Linux"\]' "${response_body}"
grep -q '"genres":\["Simulation","RPG"\]' "${response_body}"
grep -q '"aliases":\[' "${response_body}"
grep -q '"developers":\["ConcernedApe"\]' "${response_body}"
grep -q '"publishers":\["ConcernedApe"\]' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?query=DAVE%20THE%20DIVER")
[[ "${status}" == "200" ]]
grep -q '"id":"dave-the-diver"' "${response_body}"
grep -q '"page":1' "${response_body}"
grep -q '"pageSize":20' "${response_body}"
grep -q '"total":' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?page=2&pageSize=2&sort=title")
[[ "${status}" == "200" ]]
grep -q '"page":2' "${response_body}"
grep -q '"pageSize":2' "${response_body}"
[[ $(grep -o '"id"' "${response_body}" | wc -l | tr -d ' ') == "2" ]]

for sort in titleAsc titleDesc updatedDesc updatedAsc discountDesc discountAsc lowestPrice; do
    status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
        "${api_base}/api/games?pageSize=100&sort=${sort}")
    [[ "${status}" == "200" ]]
    python3 - "${response_body}" "${sort}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    games = json.load(source)["games"]

sort = sys.argv[2]
if sort == "titleAsc":
    assert games == sorted(games, key=lambda game: game["title"])
elif sort == "titleDesc":
    assert games == sorted(games, key=lambda game: game["title"], reverse=True)
elif sort in {"updatedDesc", "updatedAsc"}:
    available = [game for game in games if "lastUpdatedAt" in game]
    missing = [game for game in games if "lastUpdatedAt" not in game]
    reverse = sort == "updatedDesc"
    timestamps = [game["lastUpdatedAt"] for game in available]
    assert timestamps == sorted(timestamps, reverse=reverse)
    assert games == available + missing
elif sort in {"discountDesc", "discountAsc"}:
    available = [game for game in games if "maxDiscountPercent" in game]
    missing = [game for game in games if "maxDiscountPercent" not in game]
    reverse = sort == "discountDesc"
    discounts = [game["maxDiscountPercent"] for game in available]
    assert discounts == sorted(discounts, reverse=reverse)
    assert games == available + missing
PY
done
grep -q '"maxDiscountPercent":' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?page=0")
[[ "${status}" == "400" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?sort=unknown")
[[ "${status}" == "400" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/catalog/filters")
[[ "${status}" == "200" ]]
grep -q '"stores":.*"Steam"' "${response_body}"
grep -q '"platforms":.*"Nintendo Switch 2"' "${response_body}"
grep -q '"genres":.*"Simulation"' "${response_body}"
grep -q '"tags":.*"Farming"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?store=Google%20Play&platform=Android&genre=Simulation&tag=Farming")
[[ "${status}" == "200" ]]
grep -q '"id":"stardew-valley"' "${response_body}"
! grep -q '"id":"hades"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?store=Nintendo%20eShop")
[[ "${status}" == "200" ]]
grep -q '"id":"hades"' "${response_body}"
! grep -q '"id":"unpriced-nintendo-game"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?platform=Nintendo%20Switch")
[[ "${status}" == "200" ]]
grep -q '"id":"hades"' "${response_body}"
! grep -q '"id":"unpriced-nintendo-game"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?store=Unknown")
[[ "${status}" == "400" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/admin/catalog/status")
[[ "${status}" == "200" ]]
grep -q '"enabled":false' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"query":"Wanted Game"}' \
    "${api_base}/api/catalog-requests")
[[ "${status}" == "202" ]]
grep -q '"status":"PENDING"' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"query":"wanted game"}' \
    "${api_base}/api/catalog-requests")
[[ "${status}" == "202" ]]
grep -q '"requestCount":2' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"query":"x"}' \
    "${api_base}/api/catalog-requests")
[[ "${status}" == "400" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"appId":"1245620","apply":false}' \
    "${api_base}/api/admin/catalog/steam")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"packageName":"com.example.game","gameId":"hades","apply":false}' \
    "${api_base}/api/admin/catalog/google-play")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d '{"trackId":"123456789","gameId":"hades","apply":false}' \
    "${api_base}/api/admin/catalog/apple")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/admin/catalog/collection")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/admin/health")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/admin/catalog/metadata-sync")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -X POST "${api_base}/api/admin/catalog/collection")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/admin/catalog/sync")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -H 'Content-Type: application/json' -d '{"batchSize":20}' \
    "${api_base}/api/admin/catalog/sync")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -X PATCH -H 'Content-Type: application/json' \
    -d '{"resolution":"REJECTED"}' \
    "${api_base}/api/admin/catalog/sync/reviews/413150")
[[ "${status}" == "401" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/catalog/collection")
[[ "${status}" == "403" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/collection-runs?limit=5")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/collection-runs?limit=5")
[[ "${status}" == "403" ]]

python3 "${project_directory}/tools/set_user_role.py" \
    --database "${test_database}" \
    --email test@example.com \
    --role ADMIN >/dev/null

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/auth/me")
[[ "${status}" == "200" ]]
grep -q '"role":"ADMIN"' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/catalog/status")
[[ "${status}" == "200" ]]
grep -q '"enabled":true' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/catalog/collection")
[[ "${status}" == "200" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/health")
[[ "${status}" == "200" ]]
grep -q '"metadata"' "${response_body}"
grep -q '"notifications"' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/catalog/metadata-sync")
[[ "${status}" == "200" ]]
grep -q '"pendingReviews"' "${response_body}"

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
grep -q '"store":"Nintendo eShop"' "${response_body}"
grep -q '"platform":"Nintendo Switch 2","status":"Compatible"' "${response_body}"
grep -q '"purchaseUrl":"https://store.epicgames.com/p/hades"' "${response_body}"
grep -q '"minorAmount":25000' "${response_body}"
grep -q '"region":"KR"' "${response_body}"
grep -q '"edition":"Standard"' "${response_body}"
grep -q '"offerType":"BaseGame"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/hades/prices?platform=Nintendo%20Switch%202")
[[ "${status}" == "200" ]]
grep -q '"store":"Nintendo eShop"' "${response_body}"
! grep -q '"store":"Steam"' "${response_body}"
! grep -q '"store":"Epic Games Store"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/hades/price-history?platform=Nintendo%20Switch%202")
[[ "${status}" == "200" ]]
grep -q '"store":"Nintendo eShop"' "${response_body}"
! grep -q '"store":"Steam"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games/stardew-valley/prices?platform=Android")
[[ "${status}" == "200" ]]
grep -q '"store":"Google Play"' "${response_body}"
! grep -q '"store":"Steam"' "${response_body}"

for invalid_query in \
    "platform=invalid" \
    "region=US" \
    "edition=Collector" \
    "offerType=Rental" \
    "currency=USD"; do
    status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
        "${api_base}/api/games/hades/prices?${invalid_query}")
    [[ "${status}" == "400" ]]
done

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" \
    "${api_base}/api/collection-runs?limit=5")
[[ "${status}" == "200" ]]
grep -q '"store":"Epic Games Store"' "${response_body}"
grep -q '"productsRejected":0' "${response_body}"
grep -q '"productsFailed":0' "${response_body}"
grep -q '"retryCount":0' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" \
    "${api_base}/api/collection-runs?limit=invalid")
[[ "${status}" == "400" ]]
