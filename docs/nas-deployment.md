# NAS 비공개 베타 배포 준비

이 문서는 Docker Compose를 실행할 수 있는 NAS에서 비공개 베타를 준비하는 절차다.
Synology, QNAP, TrueNAS별 화면 설정은 NAS 모델과 운영체제를 확인한 뒤 보완한다.

## 권장 연결 구조

```text
사용자 HTTPS 요청
  → NAS reverse proxy
  → web 컨테이너(Nginx, React 정적 파일)
      → /api 요청만 api 컨테이너로 전달
          → /data/game_prices.db
          → /data/game_catalog.json
```

외부 공유기에서 Compose의 `8088` 포트를 직접 공개하지 않는다. NAS reverse proxy가
HTTPS 443 요청을 받아 내부 `8088`로 전달하도록 구성한다.

## 친구 관리자에게 확인할 항목

- NAS 모델, 운영체제 버전, CPU architecture
- Docker 또는 Container Manager 설치 여부
- SSH와 `docker compose` 실행 권한
- 컨테이너 데이터와 backup을 저장할 공유 폴더
- 사용할 도메인 또는 DDNS 주소
- HTTPS 인증서와 reverse proxy 설정 권한
- 공유기에서 외부 443 연결이 가능한지 여부

## 환경변수 준비

저장소 루트에서 예제 파일을 복사한다.

```bash
cp .env.example .env
```

운영 환경에서는 최소한 다음 값을 실제 HTTPS 주소로 변경한다.

```dotenv
APP_ENV=production
WEB_APP_URL=https://games.example.com
OAUTH_CALLBACK_BASE=https://games.example.com
COOKIE_SECURE=true
CATALOG_ADMIN_ENABLED=true
```

`.env`는 Git 추적 대상이 아니다. OAuth와 SMTP secret은 `.env` 또는 NAS secret
관리 기능에만 저장하고 채팅, 이슈, commit에 남기지 않는다. OAuth provider를
활성화할 때 client ID와 client secret을 한 쌍으로 설정한다. 운영 모드에서 HTTPS,
Secure cookie 또는 credential 한 쌍이 잘못되면 API는 오류를 출력하고 시작하지 않는다.

## 영속 데이터

Compose의 `game-price-data` volume에는 다음 두 핵심 파일이 함께 저장된다.

- `/data/game_prices.db`: 사용자, 가격 이력, 수집·알림·감사 기록
- `/data/game_catalog.json`: canonical Game과 Store 상품 연결

API 컨테이너가 처음 시작될 때 카탈로그 파일이 없으면 이미지에 포함된 검증 완료
카탈로그를 복사한다. 이후 컨테이너를 다시 만들더라도 volume의 카탈로그를 사용한다.

## 시작과 확인

```bash
docker compose config
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:8088/health
```

`docker compose config` 출력에 secret 값이 표시될 수 있으므로 외부에 공유하지 않는다.

## DB와 카탈로그 백업

```bash
docker compose --profile maintenance run --rm backup
```

이 작업은 SQLite online backup, SQLite integrity check, catalog schema check를 수행하고
동일 timestamp의 `.db`, `.catalog.json`, `.metadata.json` 파일을 `./backups`에 만든다.
metadata에는 두 파일의 SHA-256이 기록된다.

복원은 운영 파일을 바로 덮어쓰지 않고 새 경로에서 먼저 검증한다.

```bash
python3 tools/database_backup.py verify --backup backups/백업파일.db
python3 tools/database_backup.py restore \
  --backup backups/백업파일.db \
  --output work/restored_game_prices.db
python3 tools/database_backup.py restore-catalog \
  --backup backups/백업파일.catalog.json \
  --output work/restored_game_catalog.json
```

검증된 복원 파일을 실제 volume에 반영하는 작업은 API와 수집 작업을 중지한 상태에서
NAS 관리자와 함께 수행한다.

## 공개 전 확인

- 일반 사용자와 관리자 계정의 권한 분리
- 외부 HTTPS에서 login cookie 유지
- 관리자 API의 `401`/`403` 응답
- 게임 검색, 가격 조회, 알림 생성 흐름
- Store 수집 1회와 관리자 품질 대시보드
- DB·카탈로그 backup 생성과 새 경로 복원
- NAS 재부팅 후 컨테이너 자동 시작과 데이터 유지

