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

DB 적재 결과는 다음 명령으로 확인할 수 있습니다.

```sh
sqlite3 build/game_prices.db \
  "SELECT store, external_product_id, price_minor, currency FROM store_products;"
```
