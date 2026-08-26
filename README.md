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

`GameQueryService`는 게임 검색, 가격 비교, 이력 분석, 추천 결과를 하나의
application-level 응답으로 조합합니다. CLI와 향후 HTTP API는 이 서비스를
공유하므로 Domain 규칙을 각 진입점에서 다시 구현하지 않습니다.

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
./build/game_price_tracker collect --data-dir ./snapshots/latest "Stardew Valley"
./build/game_price_tracker collect-steam --data-dir ./snapshots/latest "Stardew Valley"
./build/game_price_tracker compare "Stardew Valley"
./build/game_price_tracker history "Stardew Valley"
./build/game_price_tracker history --since 2026-01-01 "Stardew Valley"
./build/game_price_tracker runs
./build/game_price_tracker search "Valley"
./build/game_price_tracker seed-demo
./build/game_price_tracker --help
```

`runs`는 `crawl_runs`에 저장된 Store별 수집 시도와 성공·실패 결과를 보여줍니다.
`search`는 로컬 게임 카탈로그에서 이름 일부가 일치하는 게임을 찾습니다.
`collect --data-dir`는 외부 수집기가 저장한 snapshot 디렉터리를 입력으로 받습니다.
디렉터리에는 Provider가 담당하는 `steam_products.txt`,
`google_play_products.txt`, `apple_app_store_products.csv`가 있어야 합니다.
`seed-demo`는 Stardew Valley의 세 Store에 2026년 1월부터 6월까지 고정된
월별 가격 6개씩을 저장합니다. 같은 명령을 다시 실행하면 기존 Demo 이력을
교체하므로 중복되지 않으며 Web 가격 추이와 추천 규칙 확인에 사용할 수 있습니다.

## Steam live collection

Steam 한 Store만 실제 응답으로 수집하는 첫 Prototype을 제공합니다. 수집기는
네트워크와 원본 보존만 담당하고, C++ `SteamProvider`가 생성된 Store 형식의
snapshot을 공통 `StoreProduct`로 변환합니다.

일반적인 실행은 수집과 SQLite 적재를 묶은 다음 한 줄 명령을 사용합니다.

```sh
python3 tools/run_steam_pipeline.py
```

이 명령은 기본적으로 `data/steam_collection_targets.json`을 수집하고,
`snapshots/latest`에 저장한 뒤 `build/game_price_tracker collect-steam-all`을
실행합니다. 다른 실행 파일이나 경로를 사용할 수도 있습니다.

```sh
python3 tools/run_steam_pipeline.py \
  --tracker build/game_price_tracker \
  --targets data/steam_collection_targets.json \
  --output-dir snapshots/latest
```

파이프라인은 같은 Snapshot 디렉터리에서 수집이 중복 실행되지 않도록 OS 파일
잠금을 사용합니다. 프로세스가 비정상 종료되어도 OS가 잠금을 해제합니다. 최근
실행 결과는 `steam_pipeline_run.json`에 수집 대상 수, 성공 수, 실패 내용,
C++ 적재 종료 코드와 함께 저장됩니다.

### macOS daily schedule

매일 오전 9시에 파이프라인을 실행하는 macOS `launchd` 설정은 다음 명령으로
프로젝트 내부에 생성할 수 있습니다. 생성만 하며 시스템에 자동 등록하지 않습니다.

```sh
python3 tools/generate_macos_schedule.py
plutil -lint snapshots/com.compgameprice.steam-collection.plist
```

시간을 바꾸려면 24시간 형식의 시·분을 전달합니다.

```sh
python3 tools/generate_macos_schedule.py --hour 21 --minute 30
```

설정을 검토한 후 실제로 등록하려면 plist를 사용자 LaunchAgents 디렉터리로
복사하고 `launchctl bootstrap`을 실행해야 합니다. 이 단계는 macOS 사용자 환경을
변경하므로 자동으로 수행하지 않습니다. 표준 출력과 오류는
`snapshots/logs/steam_pipeline.*.log`에 저장되도록 생성됩니다. 프로젝트 위치나
Python 경로가 바뀌면 plist도 다시 생성해야 합니다.

```sh
python3 tools/collect_steam_snapshot.py
./build/game_price_tracker collect-steam --data-dir snapshots/latest "Stardew Valley"
```

한 줄로 실행하려면 다음 명령을 사용합니다.

```sh
python3 tools/collect_steam_snapshot.py && ./build/game_price_tracker collect-steam --data-dir snapshots/latest "Stardew Valley"
```

설정 파일에 등록한 Steam 게임을 순차 수집할 때는 다음 명령을 사용합니다.

```sh
python3 tools/collect_steam_snapshot.py \
  --targets data/steam_collection_targets.json && \
./build/game_price_tracker collect-steam-all \
  --data-dir snapshots/latest
```

대상은 canonical Game ID와 Steam App ID의 명시적인 매핑으로 관리합니다.

```json
{
  "targets": [
    { "appId": "413150", "gameId": "stardew-valley" },
    { "appId": "105600", "gameId": "terraria" }
  ]
}
```

다중 수집은 Store에 부담을 주지 않도록 요청 사이에 기본 1초를 기다립니다. 각 게임은
일시적 실패 시 최대 3번까지 1초, 2초 간격으로 재시도하며, 한 게임의 최종 실패가
다른 게임의 수집을 중단시키지 않습니다. 실패 내용은
`steam_{appId}.error.json`에 남고 프로세스는 일부 실패를 나타내는 종료 코드 `1`을
반환합니다. 호출 간격과 재시도는 `--request-delay`, `--max-attempts`,
`--retry-delay`로 조정할 수 있습니다.

`collect-steam-all`은 `data/games.txt`에 등록된 모든 canonical Game을 순회하고,
하나의 `steam_products.txt`에서 각 Game에 해당하는 상품을 찾아 정규화합니다.
따라서 새 게임을 수집하려면 `games.txt`와 `steam_collection_targets.json` 양쪽에
동일한 canonical Game ID를 등록해야 합니다. 파이프라인은 네트워크 요청 전에 두
파일의 매핑을 검증하며, target에 Catalog에 없는 Game ID가 있으면 즉시 실패합니다.

기본 대상은 Stardew Valley Steam app `413150`, 국가 코드는 `kr`입니다. 수집기는
Python 표준 라이브러리만 사용하며 다음 파일을 원자적으로 교체합니다.

```text
snapshots/latest/
├── steam_413150.json           # Steam 원본 응답
├── steam_413150.metadata.json  # 수집 시각, URL, HTTP 상태, SHA-256
└── steam_products.txt          # SteamProvider 입력 snapshot
```

`snapshots/`는 실행 중 생성되는 데이터이므로 Git에서 제외됩니다. Steam Storefront
`appdetails` 응답은 Steamworks 공식 가격 API로 문서화된 계약이 아니므로, 응답
형식이 바뀌면 수집기가 명확히 실패하고 마지막 정상 DB 데이터는 유지하도록
분리했습니다. 대량 호출은 피하고 후속 자동화에서도 충분한 호출 간격을 둬야 합니다.
네트워크 없이 변환만 확인하려면 저장된 Fixture를 사용할 수 있습니다.

```sh
python3 tools/collect_steam_snapshot.py \
  --input tests/fixtures/steam_appdetails_413150.json \
  --output-dir snapshots/fixture
```

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
신규 상품이거나 현재가, 정상가, 할인율, 통화, 구매 가능 상태가 변경되면 `price_history`에
관측 시각과 함께 이력을 추가합니다. 동일한 데이터를 다시 적재하면 이력은
중복으로 추가되지 않습니다.
Steam live snapshot은 Provider 입력 행에 실제 수집 시각을 함께 기록하고,
Repository가 이 값을 `price_history.observed_at`으로 보존합니다. 네트워크 수집과
DB 적재 사이에 지연이 생겨도 그래프에는 응답을 관측한 시각이 사용됩니다. 기존
5개 필드 로컬 sample은 호환성을 위해 DB 적재 시각을 사용합니다. 관측 시각은
`YYYY-MM-DDTHH:MM:SS.sssZ` UTC 형식만 허용하며 잘못된 값은 트랜잭션 전체를
롤백합니다.
DB schema는 SQLite `user_version`으로 관리하며 현재 버전은 2입니다. version 2는
`store_products`와 `price_history`에 선택적인 정상가와 0–100 정수 할인율을
추가합니다. 기존 version 1 DB는 상품과 이력을 보존하면서 정상가 미상(NULL),
할인율 0으로 자동 이전됩니다. 새 DB는 바로 version 2로 초기화되며 프로그램보다 새로운 DB version은
데이터 손상을 피하기 위해 실행을 중단합니다.
`PriceHistoryService`는 저장된 이력으로 현재가, 최저가, 최고가, 정수 기반
평균가와 직전 관측 대비 가격 추이를 계산합니다.
`PurchaseRecommendationService`는 이 통계만 사용해 `StrongBuy`, `Buy`,
`Wait`, `InsufficientData` 중 하나와 판단 근거를 생성합니다. 외부 AI가
추가되더라도 가격 계산과 추천 판정은 이 결정적 규칙의 결과를 사용합니다.
추천 결과에는 역대 최저가보다 높은 금액과 비율, 평균가 대비 비율,
역대 최저·최고 범위 내 현재가 위치도 포함되어 판단 근거를 확인할 수 있습니다.

`CollectionService`는 Store별 Provider 실행을 독립적으로 관리합니다. 각 실행의
시작·종료 시각, 성공/실패, 발견 상품 수, 오류 메시지는 `crawl_runs`에
기록되며 한 Store가 실패해도 나머지 Store 수집은 계속됩니다.
Store별 최대 시도 횟수를 설정할 수 있고, 실패한 각 시도도 별도의
`crawl_runs` 레코드로 남습니다. 현재 Prototype은 지연 없이 즉시 재시도합니다.

## HTTP API

Web과 Mobile client가 같은 Core 로직을 사용하도록 Drogon 기반 read-only API를
제공합니다. macOS에서는 Drogon을 설치한 뒤 기존 빌드 명령을 실행합니다.

```sh
brew install drogon
cmake -S . -B build
cmake --build build
./build/game_price_api
```

기본 주소는 `http://127.0.0.1:8080`이며 `GAME_PRICE_API_PORT` 환경 변수로
포트를 변경할 수 있습니다.

```text
GET /health
GET /api/games?query=valley
GET /api/games/{gameId}/prices
GET /api/games/{gameId}/price-history?since=2026-01-01
GET /api/collection-runs?limit=20
```

API 응답은 가격을 `{ "minorAmount": 6500, "currency": "KRW" }`처럼 정수로
전달합니다. Drogon이 설치되지 않은 환경에서는 CLI와 테스트만 빌드되고 API
target은 생략됩니다.
현재 가격 응답과 가격 이력 관측값에는 `discountPercent`가 항상 포함되며,
Store가 정상가를 제공하면 `regularPrice`도 포함됩니다. Web 가격 카드는 할인 중인
상품의 정상가와 할인율을 표시하고 가격 그래프 Tooltip에서도 당시 할인 정보를
확인할 수 있습니다.
`collection-runs`는 최근 수집 실행을 최신순으로 반환하며 `limit`은 1–100 사이의
정수입니다. 응답에는 Store, 성공·실패 상태, 발견 상품 수, 시작·종료 시각과 실패
메시지가 포함됩니다. Web 상단의 최근 수집 실행 패널에서 같은 정보를 확인할 수
있어 자동 수집 실패를 DB나 터미널 없이 발견할 수 있습니다.
가격 이력 API는 Store별 전체 관측 시각과 정수 가격을 반환하며, `since`는
선택적인 `YYYY-MM-DD` 시작일입니다. API 통합 테스트는 실제 서버를 임시
포트에서 실행해 정상 응답과 잘못된 날짜, 없는 게임 응답을 확인합니다.

## Web client

React와 TypeScript로 만든 첫 Web 화면은 게임 검색, Store별 현재가, 최저가,
지원 Platform과 추천 상태를 API에서 조회합니다. 가격 추이는 모든 Store를
하나의 공통 축에 표시하며 Store별 색상과 클릭 가능한 범례로 구분합니다.
모든 Store는 동일한 원형 관측점과 실선을 사용합니다. 통화가 다른 Store는 가격 비교 왜곡을 막기 위해 같은 축에서
제외합니다. X축은 날짜 단위이며 같은 날 수집된 Store 가격은 같은 위치에
정렬합니다. 한 Store가 같은 날 여러 번 수집되면 마지막 관측값을 표시합니다.
관측점에 마우스를 올리거나 터치하면 포인터 옆에 Store, 날짜, 가격을 표시하며
Store 이름은 해당 그래프 선과 동일한 색상을 사용합니다.
현재가·정상가·할인율·통화·구매 가능 상태가 이전 관측과 모두 같으면 새 이력을 저장하지 않고
그래프에서도 제외하여 실제 상태 변화만 표시합니다.

API 서버를 실행한 뒤 별도 터미널에서 다음 명령을 실행합니다.

```sh
cd web
npm install
npm run dev
```

브라우저에서 `http://127.0.0.1:5173`을 열면 됩니다. API 주소를 변경할 때는
`VITE_API_URL`을 지정합니다.

```sh
VITE_API_URL=http://127.0.0.1:8080 npm run dev
```

Web production build는 다음 명령으로 확인합니다.

```sh
cd web && npm run build
```

DB 적재 결과는 다음 명령으로 확인할 수 있습니다.

```sh
sqlite3 build/game_prices.db \
  "SELECT store, external_product_id, regular_price_minor, price_minor, discount_percent, currency FROM store_products;"
```

가격 이력은 다음 명령으로 확인할 수 있습니다.

```sh
sqlite3 build/game_prices.db \
  "SELECT store, regular_price_minor, price_minor, discount_percent, currency, observed_at FROM price_history ORDER BY observed_at;"
```
