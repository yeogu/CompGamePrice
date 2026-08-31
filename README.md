# CompGamePrice

AI를 활용하여 개발하는 크로스 플랫폼 게임 가격 비교 Prototype입니다.

가격 데이터의 identity, validation, history, freshness, collection reliability와
잔여 위험은 [Data Reliability Audit](docs/data-reliability-audit.md)에 정리되어 있습니다.

서로 다른 Steam, Epic Games Store, Google Play, Apple App Store, Nintendo eShop
로컬 데이터 형식을 공통
`StoreProduct` 모델로 정규화하고, 공통 Provider 인터페이스를 통해
게임별 Store 최저가를 비교합니다.

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

## Continuous integration

GitHub Actions는 push와 pull request마다 clean Ubuntu 환경에서 C++/API를
configure·build하고, Python `unittest`, 전체 CTest integration/E2E, Web production
build를 실행합니다. 로컬에서 같은 검증을 실행하려면 Drogon, SQLite, OpenSSL,
Python 3, curl과 Node.js 22가 설치된 상태에서 다음 명령을 사용합니다.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=ON -DBUILD_GAME_PRICE_API=ON
cmake --build build --config Release --parallel \
  --target game_price_tracker game_price_api game_price_tests
python3 -m unittest discover -s tests -p 'test_*.py' -v
ctest --test-dir build --build-config Release --output-on-failure
npm --prefix web ci
npm --prefix web run build
```

CI는 repository fixture와 local sample data만 사용하며 Steam live API와 OAuth
credential을 요구하는 흐름은 실행하지 않습니다.

## Container deployment

Docker Compose는 API, same-origin Web reverse proxy와 영속 SQLite volume을
제공합니다. 로컬 또는 NAS에서 다음 명령으로 실행할 수 있습니다.

```sh
docker compose up --build -d
curl http://127.0.0.1:8088/health
```

HTTPS reverse proxy 뒤에서는 `COOKIE_SECURE=true`와 실제 `WEB_APP_URL`을 환경변수로
설정합니다. DB 백업은 maintenance profile로 명시적으로 실행합니다.

```sh
docker compose --profile maintenance run --rm backup
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

Google Play에 등록된 상품은 다음 한 줄 명령으로 KR 페이지를 수집하고
정규화한 뒤 SQLite에 반영할 수 있습니다.

```bash
python3 tools/run_google_play_pipeline.py
```

로컬 Admin 화면에서는 Store를 `Google Play`로 선택하고 게임 이름을 검색할
수 있습니다. 검색 결과는 즉시 등록되지 않으며 Preview 단계에서 다음을
검증합니다.

- Android 게임 상품인지
- KRW 유료 구매 상품인지
- Guide, Demo, Companion, Wallpaper, Soundtrack 앱이 아닌지
- 선택한 canonical Game의 제목과 일치하는지
- package name이 다른 게임에 이미 연결되지 않았는지

승인된 상품은 기존 canonical Game에 Android StoreProduct로 추가되고 즉시
Google Play 가격 수집이 시작됩니다. 신규 canonical Game을 자동 생성하지
않는 것은 잘못된 게임 identity 생성을 방지하기 위한 현재 MVP 정책입니다.

Preview의 identity 판정은 다음 정책을 사용합니다.

- `ApprovedCandidate`: 정식 제목 또는 alias와 개발사가 모두 일치
- `NeedsReview`: 제목은 일치하지만 어느 한쪽의 개발사 정보가 없음
- `Rejected`: 제목 불일치, 개발사 불일치, 비게임·무료·비KRW·제외 상품

`NeedsReview`는 실패가 아니라 자동 판정에 필요한 정보가 부족하다는 뜻입니다.
Admin 화면은 판정 근거를 한국어로 표시하고, Store 원문에서 본편·에디션·개발사
정보를 직접 확인할 체크리스트를 제공합니다. 관리자가 확인 완료 체크박스를
선택해야 등록 버튼이 활성화됩니다. `Rejected` 상품은 등록할 수 없습니다.

Apple App Store도 같은 Admin 흐름을 사용합니다. Store를
`Apple App Store`로 선택하면 iTunes Search 결과에서 Track ID, 개발사,
KRW 가격, iOS/iPadOS 지원 여부를 확인할 수 있습니다. 승인된 상품은 기존
canonical Game에 연결되고 Apple 가격 pipeline이 즉시 실행됩니다.

Apple 개발사 이름에 붙는 제한적인 법인 접미사(`LLC`, `Inc`, `Ltd` 등)는
identity 비교 시 제거하지만 일반 단어는 제거하지 않습니다. Apple Arcade처럼
직접 구매 가격이 없는 상품, 무료 앱, 비게임 앱, Guide/Demo/Soundtrack은
구매 가격 비교 상품으로 등록되지 않습니다.

각 Google Play 상품은 `data/game_catalog.json`의 안정적인 package name으로
연결됩니다. 수집은 상품별 bounded retry를 사용하며, 한 상품의 실패가 다른
상품의 snapshot 저장을 막지 않습니다. 일부 실패가 있으면 성공 데이터는
반영하되 명령은 non-zero로 종료되어 운영자가 확인할 수 있습니다.

현재 카탈로그 원본은 의도적으로 JSON을 유지합니다. 게임 identity와 Store
product mapping은 관리·검토가 필요한 작은 데이터이고 Git diff로 변경을
감사하기 쉽습니다. SQLite는 변동이 많은 가격 observation, 사용자, 알림을
담습니다. 카탈로그가 수천 건 규모가 되어 JSON reload 또는 API filtering이
병목으로 측정되면 그때 catalog table migration을 진행합니다.
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

Catalog Admin API는 기본적으로 비활성화되어 있으며, 기능을 활성화하더라도
`ADMIN` 역할로 로그인한 사용자만 접근할 수 있습니다. 먼저 일반 회원가입을 한 뒤
API를 한 번 실행해 schema를 최신 상태로 만들고 해당 계정을 승격합니다.

```sh
python3 tools/set_user_role.py \
  --email admin@example.com \
  --role ADMIN
```

관리 기능을 활성화한 API는 다음처럼 실행합니다.

```sh
CATALOG_ADMIN_ENABLED=true \
WEB_APP_URL=http://127.0.0.1:5173 \
./build/game_price_api
```

웹 사이드바의 `카탈로그 관리`에서 Steam App ID를 preview한 후 등록할 수
있습니다. 이 메뉴는 `ADMIN` 계정으로 로그인한 경우에만 표시되며, 일반 사용자가
관리 API URL을 직접 호출해도 서버가 `403 Forbidden`으로 거부합니다. 등록된
게임은 API 재시작 없이 검색에 반영됩니다. `Steam 가격 수집
시작`을 누르면 background 작업으로 전체 Steam 가격을 갱신하며 화면에서
`RUNNING`, `SUCCEEDED`, `FAILED` 상태를 확인할 수 있습니다.

같은 화면의 `Steam 자동 동기화`는 Steam 전체 App 목록에서 아직 처리하지 않은
항목을 작은 배치로 검사합니다. Steam에서 `game`으로 확인되고 제목이 명확한
일반판 본편만 자동 등록합니다. 한글 제목처럼 canonical ID를 자동 생성할 수 없는
항목과 Deluxe, DLC, Bundle 등으로 의심되는 항목은 SQLite의 검토 대기열로
분리합니다. 처리 완료 App ID와 최근 실행 결과도 SQLite에 저장되므로 다음 실행은
중단 지점 이후의 미처리 항목을 계속 검사합니다.

발견 순서는 사용자가 검색 결과 화면에서 요청한 게임, Steam 인기작·할인작·신작,
전체 App 목록 순서입니다. 검색 요청은 같은 이름을 대소문자나 공백만 바꿔 다시
요청해도 중복 행을 만들지 않고 수요 횟수만 증가합니다. 무료 게임과 비게임 상품은
가격 비교 카탈로그에서 자동 제외됩니다.

관리 화면은 검토 대기, 승인·제외 이력, 사용자 요청, 최근 동기화 실행 통계를
구분해서 보여줍니다. Steam 원본 링크에서 상품을 확인할 수 있으며 동기화는 파일
잠금으로 API와 정기 작업의 중복 실행을 방지합니다. 상세 조회의 일시적 오류와
HTTP rate limit은 최대 3회까지만 backoff 후 재시도하고, 연속 실패가 누적되면
해당 배치를 조기에 중단합니다.

모든 Store 상품 등록은 공통 안전 저장 경로를 사용합니다. 파일을 수정하기 직전에
최신 catalog를 다시 읽고, 하나의 파일 lock 안에서 Store 상품 ID와 canonical
Game identity를 검증합니다. 같은 상품을 같은 게임에 다시 연결하는 요청은
`NO_OP`으로 처리하며, 이미 다른 게임에 연결된 상품은 거부합니다. 변경 내용은
임시 파일에 기록하고 검증을 통과한 경우에만 atomic replace합니다. 파일 교체나
감사 기록 저장에 실패하면 변경 전 파일을 복원합니다.

API를 통해 실행한 catalog 변경은 SQLite의 `catalog_change_audit`에 실행 주체,
Store, 상품 ID, canonical Game ID, 변경 전후 hash와 `APPLIED`/`NO_OP` 결과로
기록됩니다. 최근 기록은 다음처럼 확인할 수 있습니다.

```sh
sqlite3 build/game_prices.db \
  "SELECT occurred_at, store, external_product_id, game_id, outcome FROM catalog_change_audit ORDER BY id DESC LIMIT 20;"
```

웹을 사용하지 않고 동일한 동기화를 실행하거나 상태를 확인할 수도 있습니다.

```sh
python3 tools/sync_steam_catalog.py --batch-size 20
python3 tools/sync_steam_catalog.py --status
```

Google Play과 Apple App Store의 canonical Game 후보도 제한된 배치로 자동
탐색할 수 있습니다. 매칭 결과는 자동 등록되지 않고 Admin 검토 큐에 저장됩니다.
동일 game/store 조합은 다시 탐색하지 않으며, 일시적인 네트워크 실패는 최대 3회만
시도합니다.

Admin 화면의 모바일 검토 큐는 canonical Game별로 Google Play와 Apple App Store
후보를 묶어 보여줍니다. 자동 승인은 제목과 유효한 KRW 본편 구매 조건에 더해
canonical Game의 개발사 또는 공식 퍼블리셔 중 하나가 Store 제공자와 일치해야
합니다. 메타데이터가 부족하면 Admin 화면에서 변경 전후 diff를 확인한 다음
개발사·퍼블리셔를 저장할 수 있으며, 변경과 Store 상품 연결은
`catalog_change_audit`에 기록됩니다.

전체 canonical Game의 신원 메타데이터 누락 여부는 다음 명령으로 점검합니다.

```bash
python3 tools/audit_catalog_metadata.py
```

자동 배포 검증에서 누락을 오류로 처리하려면 `--fail-on-incomplete`를 추가할 수
있습니다. 현재 카탈로그를 강제로 차단하지 않는 이유는 기존 prototype 게임을
안전하게 보존하면서 관리자가 검증된 정보부터 단계적으로 보완하기 위해서입니다.

연결된 Steam 본편에서 누락 메타데이터 제안을 생성하려면 다음 명령을 사용합니다.
기존 값이 없는 필드는 자동 반영되고 감사 기록에 `steam-metadata-sync` actor로
남습니다. 기존 개발사·퍼블리셔와 Steam 값이 충돌하는 경우에만 Admin의
`Steam 신원 메타데이터 보완` 검토 큐에 저장됩니다.

```bash
python3 tools/sync_steam_metadata.py
python3 tools/sync_steam_metadata.py --status
```

Admin 대시보드는 canonical 메타데이터 완성률, 최근 가격 수집 실패, 이메일 알림의
대기·재시도·재시도 소진 건수를 함께 보여줍니다. 세부 Store 연결 및 메타데이터
변경 이력은 같은 화면의 관리자 변경 기록에서 확인할 수 있습니다.

카탈로그 관리 화면은 `대시보드`, `Steam`, `Google Play`, `Apple App Store`,
`변경 기록`으로 분리됩니다. 각 Store 화면에는 해당 Store의 후보 탐색, 검토,
상품 검색·연결, 가격 수집 기능만 표시됩니다. Store 선택 dropdown은 사용하지 않아
다른 Store에 잘못 연결하는 실수를 방지합니다.

```bash
python3 tools/sync_mobile_catalog.py --store GooglePlay --batch-size 10
python3 tools/sync_mobile_catalog.py --store AppleAppStore --batch-size 10
python3 tools/sync_mobile_catalog.py --store GooglePlay --status
```

동기화는 카탈로그 발견 단계입니다. 새로 등록된 게임의 실제 현재 가격은 이후
`python3 tools/run_steam_pipeline.py` 또는 관리자 화면의 가격 수집 버튼으로
수집합니다. 자동 테스트는 Steam live API를 호출하지 않고 repository fixture를
사용합니다.

관리자는 App ID를 미리 알 필요 없이 Store와 게임 이름으로 상품 후보를 검색할
수 있습니다. 검색 결과는 `store`, `externalProductId`, `title`, `productUrl`,
`platforms`로 구성된 공통 후보 형태를 사용합니다. 현재 검색 어댑터는 Steam부터
지원하며 App ID 직접 입력은 검색 실패 시 사용하는 고급 옵션으로 남겨둡니다.

Steam과 Apple 수집, DB 반영, 수집 상태 점검, 알림 Outbox 처리를 한 번에
실행하려면 다음 운영 명령을 사용합니다. 한 단계가 실패해도 나머지 독립 단계는
계속 실행되며 마지막 JSON 요약과 종료 코드로 실패를 확인할 수 있습니다.

```bash
python3 tools/run_daily_operations.py \
  --outbox-file snapshots/notification-outbox.jsonl
```

SMTP를 사용할 때는 `--outbox-file` 대신 `SMTP_HOST`, `SMTP_FROM`과 선택적인
`SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` 환경 변수를 설정합니다. 운영 기본은
STARTTLS이며, TLS를 제공하지 않는 로컬 개발 SMTP 서버에서만
`SMTP_STARTTLS=false`를 사용합니다.

이 명령은 기본적으로 `data/game_catalog.json`의 Steam 상품을 수집하고,
`snapshots/latest`에 저장한 뒤 `build/game_price_tracker collect-steam-all`을
실행합니다. 다른 실행 파일이나 경로를 사용할 수도 있습니다.

```sh
python3 tools/run_steam_pipeline.py \
  --tracker build/game_price_tracker \
  --catalog data/game_catalog.json \
  --output-dir snapshots/latest
```

파이프라인은 같은 Snapshot 디렉터리에서 수집이 중복 실행되지 않도록 OS 파일
잠금을 사용합니다. 프로세스가 비정상 종료되어도 OS가 잠금을 해제합니다. 최근
실행 결과는 `steam_pipeline_run.json`에 수집 대상 수, 성공 수, 실패 내용,
C++ 적재 종료 코드와 함께 저장됩니다.

### macOS daily schedule

매일 오전 9시에 통합 운영 파이프라인을 실행하는 macOS `launchd` 설정은 다음 명령으로
프로젝트 내부에 생성할 수 있습니다. 생성만 하며 시스템에 자동 등록하지 않습니다.

정기 실행 순서는 Steam 인기·할인·신작 발견, 카탈로그 신규 상품 20개 검사, 전체 Steam 가격 수집,
Apple 가격 수집, 데이터 상태 점검, 알림 발송입니다. 각 단계는 독립적으로 실행되어
한 Provider가 실패해도 나머지 작업은 계속됩니다. Steam 가격 수집은 요청별 최대
3회까지만 재시도하며, 실패 항목은 다음 날 정기 실행에서 다시 시도됩니다.

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
`snapshots/logs/daily_operations.*.log`에 저장되도록 생성됩니다. 프로젝트 위치나
Python 경로가 바뀌면 plist도 다시 생성해야 합니다.

VS Code Terminal 또는 macOS Terminal에서는 관리 스크립트로 등록과 확인을 할 수
있습니다. Codex 데스크톱 앱 내부에서는 macOS sandbox가 `launchctl bootstrap`을
거부할 수 있으므로 이 명령만 일반 Terminal에서 실행합니다.

```sh
./tools/manage_macos_schedule.sh install
./tools/manage_macos_schedule.sh run
./tools/manage_macos_schedule.sh status
```

등록 해제 시 plist를 삭제하지 않고 프로젝트의 `snapshots` 아래로 이동합니다.

```sh
./tools/manage_macos_schedule.sh uninstall
```

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
  --catalog data/game_catalog.json && \
./build/game_price_tracker collect-steam-all \
  --data-dir snapshots/latest
```

게임, 지원 플랫폼과 Store 상품 매핑은 하나의 통합 카탈로그로 관리합니다.

```json
{
  "schemaVersion": 4,
  "games": [
    {
      "id": "stardew-valley",
      "title": "Stardew Valley",
      "platforms": ["Windows", "macOS", "Linux", "Android", "iOS", "iPadOS"],
      "products": [
        {
          "store": "Steam",
          "productId": "413150",
          "productUrl": "https://store.steampowered.com/app/413150",
          "platforms": ["Windows", "macOS", "Linux"],
          "region": "KR",
          "edition": "Standard",
          "offerType": "BaseGame"
        }
      ]
    }
  ]
}
```

`products` 배열은 Store 종류와 무관하게 같은 구조로 파싱됩니다. 새로운 Store는
`Store` enum과 Provider를 추가하고 이 배열에 상품을 등록하며, 기존 카탈로그 파싱
알고리즘과 가격 비교·이력·추천 서비스는 수정하지 않습니다.
현재 비교 기준은 같은 Game의 `KR + Standard + BaseGame + KRW` 상품입니다.
더 저렴하더라도 DLC, Bundle, Deluxe Edition 또는 Subscription 상품은 기본판
최저가로 선택하지 않습니다.

Epic Games Store는 첫 Store 확장 사례입니다. `epic_games_products.txt`의
colon 구분 offer block을 `EpicGamesProvider`가 정규화합니다. Hades에는 Steam과
Epic 상품이 함께 등록되어 두 PC Store의 가격 비교, 이력, 추천과 구매 링크를
동일한 Core 흐름으로 검증할 수 있습니다.

Nintendo eShop 샘플도 Hades에 연결됩니다. Nintendo Switch와 Nintendo Switch 2는
서로 다른 `Platform`이며, Switch 상품의 Switch 2 실행 가능 여부는 네이티브 플랫폼
목록에 섞지 않고 `PlatformCompatibility`로 저장합니다. 따라서 Switch 2 호환 게임,
Switch 2 전용 Edition, Upgrade Pack을 구분하면서 동일한 가격 비교 흐름을 사용합니다.

```sh
./build/game_price_tracker collect --data-dir data Hades
./build/game_price_tracker compare Hades
```

다중 수집은 Store에 부담을 주지 않도록 요청 사이에 기본 1초를 기다립니다. 각 게임은
일시적 실패 시 최대 3번까지 1초, 2초 간격으로 재시도하며, 한 게임의 최종 실패가
다른 게임의 수집을 중단시키지 않습니다. 실패 내용은
`steam_{appId}.error.json`에 남고 프로세스는 일부 실패를 나타내는 종료 코드 `1`을
반환합니다. 호출 간격과 재시도는 `--request-delay`, `--max-attempts`,
`--retry-delay`로 조정할 수 있습니다. timeout, HTTP 408/429, 5xx는 일시 오류로
분류하고 `Retry-After`가 있으면 이를 우선합니다. 잘못된 JSON, 상품 ID, 통화,
가격 표현과 그 밖의 4xx는 영구 오류로 분류해 불필요하게 재시도하지 않습니다.

`collect-steam-all`은 `data/game_catalog.json`에 등록된 모든 canonical Game을 순회하고,
하나의 `steam_products.txt`에서 각 Game에 해당하는 상품을 찾아 정규화합니다.
새 게임은 이 JSON에 Game과 Store별 `productId`를 한 번만 등록하면 됩니다.
파이프라인은 네트워크 요청 전에 필수 필드와 중복 Game/상품 ID를 검증합니다.

Steam 게임 한 개를 안전하게 추가하는 Catalog Import Prototype도 제공합니다.
기본 실행은 카탈로그를 수정하지 않고 Steam 응답에서 생성될 항목만 보여줍니다.

```sh
python3 tools/add_steam_catalog_game.py --app-id 1245620
```

출력된 제목, 플랫폼, `Standard + BaseGame` 분류가 맞는지 확인한 뒤 실제로
추가합니다. 적용 전 원본은 `data/game_catalog.json.bak`으로 보관됩니다.

```sh
python3 tools/add_steam_catalog_game.py --app-id 1245620 --apply
python3 tools/run_steam_pipeline.py
```

이 Prototype은 Steam 응답의 `type`이 `game`인 PC 상품만 허용하며 DLC 등은
거부합니다. 기존 canonical game ID, 제목 또는 Steam App ID와 중복되어도
카탈로그를 변경하지 않습니다.

여러 게임은 App ID를 한 줄에 하나씩 적은 파일로 일괄 검토합니다. `#` 뒤에는
메모를 적을 수 있습니다. 예시는 `data/steam_app_ids.example.txt`에 있습니다.

```sh
python3 tools/batch_add_steam_catalog_games.py \
  --input data/steam_app_ids.example.txt
```

모든 항목의 preview가 올바르고 거부 항목이 없을 때만 적용합니다. 하나라도
DLC, 중복 또는 잘못된 상품이면 전체 적용을 중단하므로 카탈로그가 부분적으로
변경되지 않습니다.

```sh
python3 tools/batch_add_steam_catalog_games.py \
  --input data/steam_app_ids.example.txt \
  --apply
python3 tools/run_steam_pipeline.py
```

기본 대상은 Stardew Valley Steam app `413150`, 국가 코드는 `kr`입니다. 수집기는
Python 표준 라이브러리만 사용하며 다음 파일을 원자적으로 교체합니다.

```text
snapshots/latest/
├── steam_413150.json           # Steam 원본 응답
├── steam_413150.metadata.json  # 수집 시각, URL, HTTP 상태, SHA-256
└── steam_products.txt          # SteamProvider 입력 snapshot
```

통합 파이프라인은 `latest`를 갱신하면서 원본 응답과 메타데이터를 수집 시각별로
보존합니다. 원본 JSON은 gzip으로 압축하며 App ID별 디렉터리로 분리됩니다.

```text
snapshots/archive/
└── 413150/
    ├── 20260826T000646892Z.json.gz
    └── 20260826T000646892Z.metadata.json
```

Archive는 가격이나 파서 결과를 사후 검증하고 Steam 응답 Schema 변경을 분석하기
위한 데이터입니다. `--archive-dir PATH`로 위치를 바꿀 수 있으며 파이프라인에서
생성된 모든 `snapshots/` 데이터는 Git 추적에서 제외됩니다.
기본 보관 기간은 90일이며 기간이 지난 `.json.gz`와 대응 메타데이터는 파이프라인
종료 시 삭제됩니다. `latest` Snapshot과 SQLite 가격 이력은 이 정책의 영향을 받지
않습니다. 기간은 `--archive-retention-days`로 변경할 수 있습니다.

`snapshots/logs`의 stdout과 stderr는 각각 1MB를 넘으면 최근의 완전한 로그 줄을
기준으로 약 512KB만 유지합니다. 한도는 `--log-max-bytes`, 유지 크기는
`--log-keep-bytes`로 조정합니다. 최근 실행 보고서의 `archiveFilesRemoved`와
`logsTrimmed`에서 해당 실행의 정리 결과를 확인할 수 있습니다.

### SQLite backup and restore verification

수집과 SQLite 적재가 성공하면 파이프라인은 SQLite online backup API로 일관된
백업을 `snapshots/db-backups`에 생성합니다. 각 백업은 생성 직후
`PRAGMA integrity_check`를 통과해야 하며 SHA-256, 크기, 원본 경로를 대응하는
metadata JSON에 기록합니다. 기본 보관 기간은 30일입니다.

```text
snapshots/db-backups/
├── game_prices_20260826T140446890Z.db
└── game_prices_20260826T140446890Z.metadata.json
```

백업을 수동 생성하거나 검증할 수도 있습니다.

```sh
python3 tools/database_backup.py backup
python3 tools/database_backup.py verify \
  --backup snapshots/db-backups/game_prices_YYYYMMDDTHHMMSSsssZ.db
```

복구 검증은 운영 DB를 덮어쓰지 않고 반드시 존재하지 않는 새 경로로 수행합니다.

```sh
python3 tools/database_backup.py restore \
  --backup snapshots/db-backups/game_prices_YYYYMMDDTHHMMSSsssZ.db \
  --output snapshots/restore-check.db
```

출력 경로가 이미 존재하면 복구 명령은 실패합니다. 파이프라인 보고서의
`databaseBackup`, `databaseBackupFilesRemoved`, `databaseBackupError`에서 최근
백업 결과를 확인할 수 있으며 백업 실패는 전체 파이프라인 실패로 처리됩니다.

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
DB schema는 SQLite `user_version`으로 관리하며 현재 버전은 11입니다. version 2는
`store_products`와 `price_history`에 선택적인 정상가와 0–100 정수 할인율을
추가합니다. 기존 version 1 DB는 상품과 이력을 보존하면서 정상가 미상(NULL),
할인율 0으로 자동 이전됩니다. version 3는 Store 상품에 Region, Edition,
Offer Type을 추가하며 기존 상품은 `KR`, `Standard`, `BaseGame`으로 이전합니다.
version 4는 상품별 플랫폼 호환성(예: Nintendo Switch 게임의 Switch 2 호환)을
별도 관계로 저장합니다. version 5는 사용자, 세션, 알림 규칙, 알림과 이메일
Outbox를 추가합니다. version 6는 Google, Kakao, Naver 외부 계정과 10분 만료
OAuth state를 저장합니다. version 7은 로그인 실패 횟수 제한 정보를 추가합니다.
version 8은 플랫폼별 알림 규칙과 중복 규칙 방지를 추가하고, version 9는 수집
성공·거부·실패·재시도 지표와 validation quarantine을 추가합니다. version 10은
Store product와 관측 시각 조합을 유일하게 만들며, 이전 DB에 같은 시각의 이력이
여러 개 있으면 가장 최근 row를 유지하고 나머지는 `price_history_conflicts`에
보존합니다. version 11은 상품별 마지막 확인 시각과 마지막 정상 확인 시각을
추가합니다. 마지막 정상 확인 후 48시간이 지난 가격은 stale로 표시하며 현재
최저가, 구매 추천 및 가격 알림 계산에서 제외합니다. 새 DB는 바로 version 11로
초기화되며 프로그램보다 새로운 DB version은
데이터 손상을 피하기 위해 실행을 중단합니다.
`PriceHistoryService`는 저장된 이력으로 현재가, 최저가, 최고가, 정수 기반
평균가와 직전 관측 대비 가격 추이를 계산합니다. 동일 시각의 동일 관측은
idempotent하게 처리하고, 동일 시각의 다른 값과 현재 이력보다 과거인 신규 관측은
현재 가격을 되돌리지 않도록 거부합니다. 구매 불가능 상태의 관측은 API 이력에는
남지만 최저가·평균·추천 통계에서는 제외합니다.
`PurchaseRecommendationService`는 이 통계만 사용해 `StrongBuy`, `Buy`,
`Wait`, `InsufficientData` 중 하나와 판단 근거를 생성합니다. 외부 AI가
추가되더라도 가격 계산과 추천 판정은 이 결정적 규칙의 결과를 사용합니다.
추천 결과에는 역대 최저가보다 높은 금액과 비율, 평균가 대비 비율,
역대 최저·최고 범위 내 현재가 위치도 포함되어 판단 근거를 확인할 수 있습니다.

`CollectionService`는 Store별 Provider 실행을 독립적으로 관리합니다. 각 실행의
시작·종료 시각, 성공/실패, 발견 상품 수, 오류 메시지는 `crawl_runs`에
기록되며 한 Store가 실패해도 나머지 Store 수집은 계속됩니다.
Store별 최대 시도 횟수를 설정할 수 있고, 실패한 각 시도도 별도의
`crawl_runs` 레코드로 남습니다. C++ 수집은 영구 오류를 즉시 종료하고 일시 오류만
기본 250ms부터 두 배씩, 최대 30초까지 기다리는 bounded exponential backoff로
재시도합니다.

## HTTP API

Web과 Mobile client가 같은 Core 로직을 사용하도록 Drogon 기반 API를
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
GET /api/games
GET /api/games?query=valley
GET /api/games/{gameId}/prices
GET /api/games/{gameId}/prices?platform=Windows
GET /api/games/{gameId}/price-history?since=2026-01-01
GET /api/collection-runs?limit=20
POST /api/auth/register
POST /api/auth/login
GET /api/auth/me
POST /api/auth/logout
GET, POST /api/alert-rules
DELETE /api/alert-rules/{ruleId}
GET /api/notifications
PATCH /api/notifications/{notificationId}/read
GET /api/oauth/{google|kakao|naver}/start
GET /api/oauth/{google|kakao|naver}/callback
GET /api/external-identities
DELETE /api/external-identities/{identityId}
```

비밀번호는 PBKDF2-HMAC-SHA256(무작위 salt, 210,000회 반복)으로 저장하며 원문을
보관하지 않습니다. 로그인 시 발급되는 256-bit 세션 token은 30일 후 만료되며
DB에는 SHA-256 hash만 저장합니다. 웹은 JavaScript에서 읽을 수 없는
`HttpOnly; SameSite=Lax` cookie를 사용하고, Mobile client는
`Authorization: Bearer {token}`을 사용할 수 있습니다. 운영 HTTPS 환경에서는
`COOKIE_SECURE=true`로 `Secure` 속성을 활성화해야 합니다. 같은 이메일과 client에서
15분 이내 로그인에 5번 실패하면 추가 요청은 `429 Too Many Requests`로 제한됩니다.
version 5–6에서 만든 기존 원문 세션은 version 7 이전 시 폐기되므로 한 번 다시
로그인해야 합니다.

알림 규칙은 가격 하락, 사용자 목표가 이하, 새로운 역대 최저가, 관측 평균가 이하를
지원합니다. 가격 수집 후 규칙을 평가하며 동일 관측에 대한 중복 알림은 만들지
않습니다. 기본 알림은 기본 가격 비교와 같은 `KR + Standard + BaseGame + KRW`
상품만 평가하므로 더 저렴한 DLC, Bundle, Subscription, Deluxe Edition이 본편
알림을 발생시키지 않습니다. 플랫폼과 freshness 필터도 동일하게 적용됩니다.
향후 Edition이나 Offer Type별 알림이 필요하면 이 비교 identity를 알림 규칙에
명시적으로 추가할 수 있지만 현재 MVP는 기본 본편 알림만 제공합니다.
알림은 웹 알림함에 즉시 저장되고 `notification_outbox`에도 `PENDING`
상태로 쌓입니다. 실제 이메일 발송은 이후 SMTP 또는 메일 API worker가 Outbox를
처리하도록 분리되어 있습니다. 발송 실패는 최대 3회까지 지수 backoff로 재시도하며
`attempt_count`, `last_error`, `last_attempt_at`, `next_attempt_at`에 운영 정보를
남깁니다. 재시도 한도를 넘긴 항목은 자동으로 다시 보내지 않습니다.

현재 Outbox 상태만 확인할 때는 실제 메일 credential이 필요하지 않습니다.

```bash
python3 tools/dispatch_notification_outbox.py \
  --database build/game_prices.db \
  --status
```

소셜 로그인은 Authorization Code flow와 Provider별 고유 사용자 ID를 사용합니다.
Provider가 같은 이메일을 반환하더라도 기존 계정을 자동 병합하지 않으며, 로그인된
상태에서 `start?link=true`로 시작한 경우에만 명시적으로 연결합니다. Client Secret은
Git에 저장하지 않고 다음 환경 변수로 전달합니다.

```sh
export GOOGLE_OAUTH_CLIENT_ID="..."
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export KAKAO_OAUTH_CLIENT_ID="..."
export KAKAO_OAUTH_CLIENT_SECRET="..." # Kakao 설정에서 Client Secret 사용 시
export NAVER_OAUTH_CLIENT_ID="..."
export NAVER_OAUTH_CLIENT_SECRET="..."
export OAUTH_CALLBACK_BASE="http://127.0.0.1:8080"
export WEB_APP_URL="http://127.0.0.1:5173"
export COOKIE_SECURE="false" # 운영 HTTPS에서는 true
./build/game_price_api
```

각 Provider 개발자 Console에는 정확히 다음 callback을 등록해야 합니다.

```text
http://127.0.0.1:8080/api/oauth/google/callback
http://127.0.0.1:8080/api/oauth/kakao/callback
http://127.0.0.1:8080/api/oauth/naver/callback
```

API 응답은 가격을 `{ "minorAmount": 6500, "currency": "KRW" }`처럼 정수로
전달합니다. Drogon이 설치되지 않은 환경에서는 CLI와 테스트만 빌드되고 API
target은 생략됩니다.
가격 상품에는 각 Store의 실제 상품 페이지를 가리키는 `purchaseUrl`이 포함됩니다.
가격 API는 `platform`, `region`, `edition`, `offerType`, `currency` 비교 조건을
query parameter로 받습니다. 생략하면 `KR + Standard + BaseGame + KRW`가 기본이며
현재 지원하지 않는 값은 `400 Bad Request`를 반환합니다.
현재 가격 응답과 가격 이력 관측값에는 `discountPercent`가 항상 포함되며,
Store가 정상가를 제공하면 `regularPrice`도 포함됩니다. Web 가격 카드는 할인 중인
상품의 정상가와 할인율을 표시하고 가격 그래프 Tooltip에서도 당시 할인 정보를
확인할 수 있습니다.
`collection-runs`는 최근 수집 실행을 최신순으로 반환하며 `limit`은 1–100 사이의
정수입니다. 응답에는 Store, 성공 상품 수(`productsFound`), 검증 거부 수
(`productsRejected`), Provider 실패 수(`productsFailed`), 재시도 수(`retryCount`),
시작·종료 시각과 오류 메시지가 포함됩니다. 정규화된 record 하나가 잘못된 경우
정상 record는 저장하고 거부된 record와 사유는 `collection_rejections`에 격리합니다.
Steam·Epic·Nintendo·Google Play·Apple App Store의 local 입력도 파일 전체를
폐기하지 않고 식별 가능한 Game별 행 또는 block 단위로 parsing 오류를 격리합니다.
파일을 열 수 없는 경우처럼 record로 분리할 수 없는 오류만 Provider 전체 실패가 됩니다.
Web 상단의 최근 수집 실행 패널에서도 같은 요약을 확인할 수 있습니다.
가격 이력 API는 Store별 전체 관측 시각과 정수 가격을 반환하며, `since`는
선택적인 `YYYY-MM-DD` 시작일입니다. API 통합 테스트는 실제 서버를 임시
포트에서 실행해 정상 응답과 잘못된 날짜, 없는 게임 응답을 확인합니다.

## Web client

React와 TypeScript로 만든 첫 Web 화면은 통합 카탈로그의 전체 게임 목록, 게임 검색, Store별 현재가, 최저가,
지원 Platform과 추천 상태를 API에서 조회합니다. 가격 추이는 모든 Store를
하나의 공통 축에 표시하며 Store별 색상과 클릭 가능한 범례로 구분합니다.
모든 Store는 동일한 원형 관측점과 실선을 사용합니다. 통화가 다른 Store는 가격 비교 왜곡을 막기 위해 같은 축에서
제외합니다. X축은 날짜 단위이며 같은 날 수집된 Store 가격은 같은 위치에
정렬합니다. 한 Store가 같은 날 여러 번 수집되면 마지막 관측값을 표시합니다.
관측점에 마우스를 올리거나 터치하면 포인터 옆에 Store, 날짜, 가격을 표시하며
Store 이름은 해당 그래프 선과 동일한 색상을 사용합니다.
각 가격 카드에는 상품의 Region, Edition과 Offer Type도 함께 표시합니다.
가격 카드의 추천 영역은 추천 등급뿐 아니라 역대 최저가와의 금액·비율 차이와
판단 근거를 함께 표시합니다. 현재 규칙 기반 추천은 설명 가능하고 테스트 가능한
기준선이며, 향후 AI 추천은 이 결과를 근거 데이터로 사용할 수 있습니다.
회원가입·로그인 후 선택한 게임에 가격 알림을 등록하고, 발생한 알림을 사용자별
알림함에서 확인하거나 읽음 처리할 수 있습니다.
게임을 선택하면 `?game=hollow-knight` 형태로 현재 주소가 갱신되므로 특정 게임
화면을 북마크하거나 공유할 수 있습니다. 가격 카드의 Store 링크는 API가 제공한
공식 상품 페이지를 새 탭으로 엽니다.
플랫폼 버튼을 선택하면 해당 플랫폼을 지원하는 가격 카드와 그래프만 남고,
`?game=hades&platform=Windows`처럼 선택 상태가 공유 주소에도 포함됩니다.
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
