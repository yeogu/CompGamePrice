#!/usr/bin/env bash
set -euo pipefail
trap 'echo "API integration failed at line ${LINENO}" >&2' ERR

api_binary="$1"
tracker_binary="$2"
curl_binary="$3"
api_port=19081
api_base="http://127.0.0.1:${api_port}"
response_body="/tmp/game_price_api_response_$$.json"
test_database="/tmp/game_price_api_test_$$.db"
test_catalog="/tmp/game_price_api_catalog_$$.json"
cookie_jar="/tmp/game_price_api_cookie_$$.txt"
member_cookie_jar="/tmp/game_price_api_member_cookie_$$.txt"
project_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

cleanup() {
    if [[ -n "${api_pid:-}" ]]; then kill "${api_pid}" 2>/dev/null || true; fi
    rm -f "${response_body}" "${cookie_jar}" "${member_cookie_jar}" "${test_catalog}" "${test_database}" "${test_database}-shm" "${test_database}-wal"
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
catalog["games"].append({
    "id": "runtime-switch2-compatible-game",
    "title": "Runtime Switch 2 Compatible Game",
    "platforms": ["NintendoSwitch"],
    "genres": ["Test"],
    "tags": [],
    "aliases": [],
    "developers": ["Test"],
    "publishers": ["Test"],
    "products": [{
        "store": "NintendoEShop",
        "productId": "runtime-switch2-compatible",
        "productUrl": "https://example.invalid/runtime-switch2-compatible",
        "platforms": ["NintendoSwitch"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }],
})
catalog["games"].append({
    "id": "bundle-price-test",
    "title": "Bundle Price Test",
    "platforms": ["PlayStation5", "iOS"],
    "genres": ["Test"],
    "tags": [],
    "aliases": [],
    "developers": ["Test Studio"],
    "publishers": ["Test Publisher"],
    "products": [{
        "store": "PlayStationStore",
        "productId": "BASE-GAME",
        "productUrl": "https://example.invalid/base-game",
        "platforms": ["PlayStation5"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }, {
        "store": "PlayStationStore",
        "productId": "TWO-GAME-BUNDLE",
        "productUrl": "https://example.invalid/two-game-bundle",
        "platforms": ["PlayStation5"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "Bundle",
        "offerName": "Jennie Bundle",
    }, {
        "store": "AppleAppStore",
        "productId": "mobile-free-download",
        "productUrl": "https://example.invalid/mobile-free-download",
        "platforms": ["iOS"],
        "region": "KR",
        "edition": "Standard",
        "offerType": "BaseGame",
    }],
})
with open(sys.argv[2], "w", encoding="utf-8") as output:
    json.dump(catalog, output)
PY

GAME_PRICE_DATABASE_PATH="${test_database}" "${tracker_binary}" seed-demo >/dev/null
python3 - "${test_database}" <<'PY'
from datetime import datetime, timezone
import sqlite3
import sys

now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute(
        "INSERT INTO games(id, title, normalized_title) VALUES(?, ?, ?)",
        ("bundle-price-test", "Bundle Price Test", "bundle price test"),
    )
    connection.executemany(
        """
        INSERT INTO store_products(
            store, external_product_id, game_id, price_minor,
            regular_price_minor, discount_percent, currency, purchasable,
            region, edition, offer_type, last_checked_at,
            last_successful_check_at
        ) VALUES(?, ?, ?, ?, ?, ?, 'KRW', 1, 'KR', 'Standard', ?, ?, ?)
        """,
        [
            ("PlayStation Store", "BASE-GAME", "bundle-price-test", 47000, 47000, 0, "BaseGame", now, now),
            ("PlayStation Store", "TWO-GAME-BUNDLE", "bundle-price-test", 23760, 72000, 67, "Bundle", now, now),
        ],
    )
    connection.executemany(
        "INSERT INTO product_platforms(store, external_product_id, platform) VALUES('PlayStation Store', ?, 'PlayStation 5')",
        [("BASE-GAME",), ("TWO-GAME-BUNDLE",)],
    )
    connection.execute(
        "INSERT INTO games(id, title, normalized_title) VALUES(?, ?, ?)",
        ("runtime-switch2-compatible-game", "Runtime Switch 2 Compatible Game",
         "runtime switch 2 compatible game"),
    )
    connection.execute("""
        INSERT INTO store_products(
            store, external_product_id, game_id, price_minor,
            regular_price_minor, discount_percent, currency, purchasable,
            region, edition, offer_type, last_checked_at,
            last_successful_check_at
        ) VALUES('Nintendo eShop', 'runtime-switch2-compatible', ?,
                 28600, 28600, 0, 'KRW', 1, 'KR', 'Standard',
                 'BaseGame', ?, ?)
    """, ("runtime-switch2-compatible-game", now, now))
    connection.execute("""
        INSERT INTO product_platforms(store, external_product_id, platform)
        VALUES('Nintendo eShop', 'runtime-switch2-compatible', 'Nintendo Switch')
    """)
    connection.execute("""
        INSERT INTO product_compatibility(
            store, external_product_id, platform, status)
        VALUES('Nintendo eShop', 'runtime-switch2-compatible',
               'Nintendo Switch 2', 'Compatible')
    """)
PY
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
    "${api_base}/api/games/bundle-price-test/prices")
[[ "${status}" == "200" ]]
python3 - "${response_body}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    products = json.load(source)["products"]

assert len(products) == 2
bundle = next(product for product in products if product["offerType"] == "Bundle")
assert bundle["offerName"] == "Jennie Bundle"
assert bundle["price"]["minorAmount"] == 23760
assert bundle["regularPrice"]["minorAmount"] == 72000
assert bundle["effectiveAllocatedPrice"]["minorAmount"] == 15510
assert bundle["effectivePriceMethod"] == "ProportionalToStandaloneRegularPrice"
PY

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
grep -q '"games":\[' "${response_body}"
grep -q '"total":' "${response_body}"

while IFS='|' read -r query game_id; do
    status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
        "${api_base}/api/games?query=${query}")
    [[ "${status}" == "200" ]]
    grep -q "\"id\":\"${game_id}\"" "${response_body}"
done <<'EOF'
Stardew%20Valley|stardew-valley
Terraria|terraria
Hollow%20Knight|hollow-knight
Hades|hades
EOF

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?query=Stardew%20Valley")
[[ "${status}" == "200" ]]
python3 - "${response_body}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    game = json.load(source)["games"][0]

assert {"Windows", "macOS", "Linux"}.issubset(game["platforms"])
assert {"Simulation", "RPG"}.issubset(game["genres"])
assert isinstance(game["aliases"], list)
assert "ConcernedApe" in game["developers"]
assert "ConcernedApe" in game["publishers"]
PY

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
python3 - "${response_body}" "${test_catalog}" <<'PY'
import json
import sys
with open(sys.argv[1]) as source:
    response = json.load(source)
with open(sys.argv[2]) as source:
    catalog = json.load(source)
expected = sorted(catalog['games'], key=lambda game: (game['title'], game['id']))
assert response['total'] == len(expected)
assert [game['id'] for game in response['games']] == [game['id'] for game in expected[2:4]]
PY

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?page=100000&pageSize=12&sort=titleAsc")
[[ "${status}" == "200" ]]
python3 - "${response_body}" <<'PY'
import json
import sys
with open(sys.argv[1]) as source:
    response = json.load(source)
assert response['games'] == [] and response['total'] > 0
PY

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
grep -q '"stores":.*"PlayStation Store"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/home")
[[ "${status}" == "200" ]]
python3 - "${response_body}" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as source:
    home = json.load(source)
assert set(home) == {"deals", "historicalLows", "recentlyAdded"}
assert all(isinstance(home[section], list) for section in home)
for section in home.values():
    for game in section:
        assert game["priceStatus"] == "Available"
        assert game["lowestPrice"]["minorAmount"] > 0
        assert game["lowestPrice"]["currency"] == "KRW"
PY
grep -q '"stores":.*"Microsoft Store"' "${response_body}"
grep -q '"platforms":.*"Nintendo Switch 2"' "${response_body}"
grep -q '"platforms":.*"PlayStation 4"' "${response_body}"
grep -q '"platforms":.*"PlayStation 5"' "${response_body}"
grep -q '"platforms":.*"Xbox One"' "${response_body}"
grep -q '"platforms":.*"Xbox Series X|S"' "${response_body}"
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
    "${api_base}/api/games?platform=Nintendo%20Switch%202")
[[ "${status}" == "200" ]]
grep -q '"id":"runtime-switch2-compatible-game"' "${response_body}"
grep -q '"platforms":.*"Nintendo Switch 2"' "${response_body}"

python3 - "${test_database}" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1], timeout=5) as connection:
    connection.execute(
        "UPDATE store_products SET last_successful_check_at = ? "
        "WHERE game_id = ? AND store IN ('Steam', 'Epic Games Store')",
        ("2000-01-01T00:00:00.000Z", "hades"),
    )
PY
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?platform=Windows&pageSize=100")
[[ "${status}" == "200" ]]
python3 - "${response_body}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    games = json.load(source)["games"]

hades = next(game for game in games if game["id"] == "hades")
assert hades["priceStatus"] == "Stale"
assert "lowestPrice" not in hades
PY

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
    "${api_base}/api/admin/catalog/integrity")
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
    -c "${member_cookie_jar}" \
    -H 'Content-Type: application/json' \
    -d '{"email":"member@example.com","password":"member-password-123"}' \
    "${api_base}/api/auth/register")
[[ "${status}" == "201" ]]
member_id=$(grep -o '"id":[0-9]*' "${response_body}" | head -1 | cut -d ':' -f 2)
[[ -n "${member_id}" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/users?q=member%40example.com")
[[ "${status}" == "200" ]]
grep -q '"email":"member@example.com"' "${response_body}"
grep -q '"status":"ACTIVE"' "${response_body}"
grep -q '"total":1' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" \
    -X PATCH -H 'Content-Type: application/json' -d '{"active":false}' \
    "${api_base}/api/admin/users/${member_id}/status")
[[ "${status}" == "400" ]]
grep -q 'suspension reason is required' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" \
    -X PATCH -H 'Content-Type: application/json' \
    -d '{"active":false,"reason":"Integration test policy violation"}' \
    "${api_base}/api/admin/users/${member_id}/status")
[[ "${status}" == "200" ]]
grep -q '"status":"SUSPENDED"' "${response_body}"
grep -q '"suspensionReason":"Integration test policy violation"' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${member_cookie_jar}" "${api_base}/api/auth/me")
[[ "${status}" == "401" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" \
    -X PATCH -H 'Content-Type: application/json' -d '{"active":true}' \
    "${api_base}/api/admin/users/${member_id}/status")
[[ "${status}" == "200" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" -X POST \
    "${api_base}/api/admin/users/${member_id}/password-reset")
[[ "${status}" == "202" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/users/audits")
[[ "${status}" == "200" ]]
grep -q '"action":"SUSPEND_USER"' "${response_body}"
grep -q '"action":"SEND_PASSWORD_RESET"' "${response_body}"
grep -q '"targetEmail":"member@example.com"' "${response_body}"
grep -q '"actorEmail":"test@example.com"' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/catalog/collection")
[[ "${status}" == "200" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/health")
[[ "${status}" == "200" ]]
grep -q '"metadata"' "${response_body}"
grep -q '"notifications"' "${response_body}"
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/admin/catalog/integrity")
[[ "${status}" == "200" ]]
grep -q '"issueCount":' "${response_body}"
grep -q '"type":"MISSING_PRICE"' "${response_body}"
grep -q '"gameId":"unpriced-nintendo-game"' "${response_body}"
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
python3 - "${response_body}" <<'PY'
import json
import sys
with open(sys.argv[1]) as source:
    report = json.load(source)
assert all(product["store"] != "Epic Games Store" for product in report["products"])
assert any(link["store"] == "Epic Games Store" and link["purchaseUrl"] == "https://store.epicgames.com/p/hades" for link in report["purchaseLinks"])
assert report.get("cheapest", {}).get("store") != "Epic Games Store"
PY
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

# A background catalog update must become searchable without an API restart.
python3 - "${api_base}" "${test_database}" <<'PY'
import json
import sqlite3
import sys
import time
from urllib.request import urlopen

url = sys.argv[1] + '/api/games?query=Background%20New%20Game&pageSize=12'
def fetch():
    with urlopen(url) as response:
        assert 'app;dur=' in response.headers['Server-Timing']
        assert response.headers['Cache-Control'] == 'no-store'
        return response.headers['X-Search-Cache'], json.load(response)

assert fetch()[0] == 'MISS'
assert fetch()[0] == 'HIT'
with sqlite3.connect(sys.argv[2]) as connection:
    connection.execute("UPDATE store_products SET last_checked_at='2026-01-01T00:00:00Z' WHERE rowid=(SELECT MIN(rowid) FROM store_products)")
assert fetch()[0] == 'MISS', 'External collector writes must invalidate search cache'
assert fetch()[0] == 'HIT'
time.sleep(10.1)
assert fetch()[0] == 'MISS', 'Cache must expire even when the database is unchanged'
# Warm the exact key used after replacing the catalog below, including empty results.
with sqlite3.connect(sys.argv[2]) as connection:
    connection.execute("""INSERT INTO store_products(
        store,external_product_id,game_id,price_minor,currency,purchasable,region,edition,offer_type,last_successful_check_at)
        VALUES('Apple App Store','mobile-free-download','bundle-price-test',0,'KRW',1,'KR','Standard','BaseGame',
        strftime('%Y-%m-%dT%H:%M:%fZ','now'))""")
with urlopen(sys.argv[1] + '/api/games?query=Bundle%20Price%20Test') as response:
    game = json.load(response)['games'][0]
    assert game['lowestPrice']['minorAmount'] > 0, 'Mobile downloads must not become a zero full-game price'
with urlopen(sys.argv[1] + '/api/games?query=Bundle%20Price%20Test&store=Apple%20App%20Store') as response:
    game = json.load(response)['games'][0]
    assert game['priceStatus'] == 'DownloadOnly'
    assert 'lowestPrice' not in game
with urlopen(sys.argv[1] + '/api/games?query=Background%20New%20Game') as response:
    assert json.load(response)['games'] == []
PY
python3 - "${test_catalog}" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
document = json.loads(path.read_text())
game = dict(document["games"][0])
game.update(id="background-new-game", title="Background New Game", aliases=[])
game["products"] = [{"store": "Steam", "productId": "999999991", "productUrl": "https://store.steampowered.com/app/999999991", "platforms": ["Windows"], "region": "KR", "edition": "Standard", "offerType": "BaseGame"}]
game["platforms"] = ["Windows"]
document["games"].append(game)
temporary = path.with_suffix(".next")
temporary.write_text(json.dumps(document))
temporary.replace(path)
PY
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?query=Background%20New%20Game")
[[ "${status}" == "200" ]]
grep -q '"id":"background-new-game"' "${response_body}"

# An invalid replacement must preserve the last valid in-memory catalog.
python3 - "${test_catalog}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
temporary = path.with_suffix(".next")
temporary.write_text('{"games": invalid}')
temporary.replace(path)
PY
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    "${api_base}/api/games?query=Background%20New%20Game")
[[ "${status}" == "200" ]]
grep -q '"id":"background-new-game"' "${response_body}"

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" \
    "${api_base}/api/collection-runs?limit=invalid")
[[ "${status}" == "400" ]]

status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" -H 'Content-Type: application/json' -X DELETE \
    -d '{"confirmation":"wrong@example.com"}' \
    "${api_base}/api/account")
[[ "${status}" == "400" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" -H 'Content-Type: application/json' -X DELETE \
    -d '{"confirmation":"test@example.com"}' \
    "${api_base}/api/account")
[[ "${status}" == "200" ]]
status=$("${curl_binary}" -sS -o "${response_body}" -w '%{http_code}' \
    -b "${cookie_jar}" "${api_base}/api/auth/me")
[[ "${status}" == "401" ]]
