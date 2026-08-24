# CompGamePrice

AI를 활용하여 개발하는 크로스 플랫폼 게임 가격 비교 Prototype입니다.

서로 다른 Steam, Google Play, Apple App Store 로컬 데이터 형식을 공통
`StoreProduct` 모델로 정규화하고, 공통 Provider 인터페이스를 통해
Stardew Valley의 최저가를 비교합니다.

## Build and run

```sh
cmake -S . -B build
cmake --build build
./build/game_price_tracker
```

C++17과 SQLite3 개발 라이브러리가 필요합니다. 실행하면 Provider가 정규화한
상품 데이터가 빌드 디렉터리의 `game_prices.db`에 저장됩니다.
가격 비교 서비스는 Provider를 직접 조회하지 않고, 적재가 끝난 SQLite DB에서
정규화된 상품을 다시 읽어 최저가를 계산합니다.
신규 상품이거나 가격, 통화, 구매 가능 상태가 변경되면 `price_history`에
관측 시각과 함께 이력을 추가합니다. 동일한 데이터를 다시 적재하면 이력은
중복으로 추가되지 않습니다.

DB 적재 결과는 다음 명령으로 확인할 수 있습니다.

```sh
sqlite3 build/game_prices.db \
  "SELECT store, external_product_id, price_minor, currency FROM store_products;"
```

가격 이력은 다음 명령으로 확인할 수 있습니다.

```sh
sqlite3 build/game_prices.db \
  "SELECT store, price_minor, currency, observed_at FROM price_history ORDER BY observed_at;"
```
