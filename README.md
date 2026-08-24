# CompGamePrice

AI를 활용하여 개발하는 크로스 플랫폼 게임 가격 비교 Prototype입니다.

서로 다른 Steam, Google Play, Apple App Store 로컬 데이터 형식을 공통
`StoreProduct` 모델로 정규화하고, 공통 Provider 인터페이스를 통해
Stardew Valley의 최저가를 비교합니다.

## Project structure

```text
include/game_price/
├── domain/          # Game, StoreProduct, Money 등 핵심 모델
├── app/             # CLI 명령과 입력 해석
├── catalog/         # 게임 이름과 canonical Game 조회
├── collection/      # Store Provider, 수집 실행과 상태 기록
├── persistence/     # SQLite 연결과 Repository
├── pricing/         # 가격 비교와 가격 이력 분석
├── recommendation/  # 구매 추천 규칙과 결과
└── support/         # 공통 문자열 처리 도구

src/                 # include 구조와 대응하는 구현 파일
tests/               # CTest에서 실행하는 자동화 테스트
```

## Build and run

```sh
cmake -S . -B build
cmake --build build
./build/game_price_tracker
```

인자 없이 실행하면 수집, 비교, 이력 분석을 모두 수행합니다. 외부 스케줄러와
조회 작업을 분리할 때는 다음 CLI 명령을 사용합니다.

```sh
./build/game_price_tracker collect "Stardew Valley"
./build/game_price_tracker compare "Stardew Valley"
./build/game_price_tracker history "Stardew Valley"
./build/game_price_tracker runs
./build/game_price_tracker search "Valley"
./build/game_price_tracker --help
```

`runs`는 `crawl_runs`에 저장된 Store별 수집 시도와 성공·실패 결과를 보여줍니다.
`search`는 로컬 게임 카탈로그에서 이름 일부가 일치하는 게임을 찾습니다.

프로세스 종료 코드는 자동 실행 환경에서 결과를 구분할 수 있도록 정의되어 있다.

- `0`: 성공
- `1`: 실행 중 오류
- `2`: 잘못된 명령
- `3`: 게임을 찾을 수 없음
- `4`: 저장된 가격 데이터 없음
- `5`: 하나 이상의 Store 수집 최종 실패

빌드와 전체 테스트는 한 줄로 실행할 수 있습니다.

```sh
cmake --build build && ctest --test-dir build --output-on-failure
```

C++17과 SQLite3 개발 라이브러리가 필요합니다. 실행하면 Provider가 정규화한
상품 데이터가 빌드 디렉터리의 `game_prices.db`에 저장됩니다.
가격 비교 서비스는 Provider를 직접 조회하지 않고, 적재가 끝난 SQLite DB에서
정규화된 상품을 다시 읽어 최저가를 계산합니다.
신규 상품이거나 가격, 통화, 구매 가능 상태가 변경되면 `price_history`에
관측 시각과 함께 이력을 추가합니다. 동일한 데이터를 다시 적재하면 이력은
중복으로 추가되지 않습니다.
`PriceHistoryService`는 저장된 이력으로 현재가, 최저가, 최고가, 정수 기반
평균가와 직전 관측 대비 가격 추이를 계산합니다.
`PurchaseRecommendationService`는 이 통계만 사용해 `StrongBuy`, `Buy`,
`Wait`, `InsufficientData` 중 하나와 판단 근거를 생성합니다. 외부 AI가
추가되더라도 가격 계산과 추천 판정은 이 결정적 규칙의 결과를 사용합니다.

`CollectionService`는 Store별 Provider 실행을 독립적으로 관리합니다. 각 실행의
시작·종료 시각, 성공/실패, 발견 상품 수, 오류 메시지는 `crawl_runs`에
기록되며 한 Store가 실패해도 나머지 Store 수집은 계속됩니다.
Store별 최대 시도 횟수를 설정할 수 있고, 실패한 각 시도도 별도의
`crawl_runs` 레코드로 남습니다. 현재 Prototype은 지연 없이 즉시 재시도합니다.

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
