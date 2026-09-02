# NAS 비공개 베타 배포 준비

이 문서는 Docker Compose를 실행할 수 있는 NAS에서 비공개 베타를 준비하는 절차다.
Synology, QNAP, TrueNAS별 화면 설정은 NAS 모델과 운영체제를 확인한 뒤 보완한다.

현재 검증한 Synology 환경은 DSM 7.1, Docker 20.10, legacy
`docker-compose` 1.28 조합이다. 이 환경에서는 `docker compose` 대신
`/usr/local/bin/docker-compose`를 사용하고 Compose 파일을 `-f`로 명시한다.

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

구형 Synology Docker에서 bridge DNS 또는 컨테이너 간 통신이 실패하면 NAS 전체
방화벽을 임의로 수정하지 않는다. `compose.synology.yml`은 API와 web을 host network로
실행하고, API는 `127.0.0.1:8080`에만 바인딩하며 web만 `8088`에서 수신한다.

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

현재 비공개 베타 UI는 이메일 회원가입과 로그인만 제공한다. Google, Kakao, Naver
OAuth API 구현은 보존하지만 provider 설정과 운영 검증이 끝나기 전에는 UI에 노출하지 않는다.

비밀번호 찾기는 기존 비밀번호를 발송하지 않는다. 30분 동안 한 번만 사용할 수 있는
재설정 링크를 `email_outbox`에 저장하고 mailer가 SMTP로 전달한다. `.env`의
`SMTP_HOST`, `SMTP_FROM`을 반드시 설정하고, SMTP 인증이 필요하면
`SMTP_USERNAME`, `SMTP_PASSWORD`도 설정한다. 비밀번호 변경이 완료되면 기존 로그인
세션과 사용하지 않은 다른 재설정 토큰도 모두 폐기된다.
관리자 운영 상태 화면에서는 가격 알림 메일과 계정 이메일을 분리해 대기, 재시도,
재시도 소진 및 최근 오류를 확인할 수 있다.

현재 베타의 서비스 발신 계정은 별도로 만든 Google 계정을 사용한다.
Google 개인 계정의 이메일 도메인은 `google.com`이 아니라 `gmail.com`이다.
아래 주소가 실제로 생성된 뒤 정확한 주소와 Google 앱 비밀번호를 NAS `.env`에만
입력한다.

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_FROM=dealquest92@gmail.com
SMTP_USERNAME=dealquest92@gmail.com
SMTP_PASSWORD=Google-앱-비밀번호
SMTP_STARTTLS=true
SMTP_SSL=false
EMAIL_DISPATCH_INTERVAL_SECONDS=30
```

## 가격 수집 자동화

Compose의 `collector` 서비스는 API가 정상 상태가 된 뒤 Steam, Google Play,
Apple App Store의 카탈로그 탐색과 가격 수집을 실행한다. 기본 주기는 6시간이며
`.env`에서 조정할 수 있다.

```dotenv
COLLECTION_INTERVAL_SECONDS=21600
COLLECTION_INITIAL_DELAY_SECONDS=120
COLLECTION_CATALOG_BATCH_SIZE=20
COLLECTION_ENABLED=true
```

- 한 Store의 수집 실패는 다른 Store 수집을 중단하지 않는다.
- 동일 volume에서는 OS 파일 잠금으로 scheduler 중복 실행을 차단한다.
- 실패한 실행을 무한 재시도하지 않고 다음 정기 주기에 다시 시도한다.
- Store 요청 과부하를 방지하기 위해 주기는 300초 미만으로 설정할 수 없다.
- 세부 수집 결과는 기존 collection run과 관리자 운영 상태 화면에서 확인한다.
- Steam 후보는 인기·할인·신작 공개 목록을 각각 3페이지까지 탐색한다. 폐기된
  `ISteamApps/GetAppList/v2`는 사용하지 않으므로 별도 Steam Web API key가 필요 없다.
- Google Play와 Apple App Store의 검색 결과 없음·거절 항목은 7일 후 다시 검사한다.
  자동 연결 또는 검토 대기 항목은 중복 탐색하지 않는다.
- 관리자 대시보드는 Store별 최근 처리·자동 등록·검토·제외·실패 건수와 최근 7일
  카탈로그 증가량을 표시한다.

점검이나 Store 장애로 자동 수집을 잠시 멈출 때는 `.env`를 변경하고 컨테이너를
다시 만든다. 기존 가격과 이력은 삭제되지 않으며 관리자 운영 상태에는 `중지됨`으로
표시된다.

```dotenv
COLLECTION_ENABLED=false
```

재개할 때는 값을 `true`로 되돌린 뒤 같은 방식으로 컨테이너를 다시 만든다.

배포 후 자동 수집 컨테이너와 최근 로그를 확인한다.

```bash
sudo /usr/local/bin/docker-compose -f compose.synology.yml ps
sudo /usr/local/bin/docker-compose -f compose.synology.yml logs --tail 100 collector
```

즉시 한 번 확인할 때는 동일한 전체 실행 잠금을 사용하는 `--once` 모드로 실행한다.
정기 수집이 이미 진행 중이면 중복 실행하지 않고 종료한다.

```bash
sudo docker exec compgameprice_collector_1 \
  python3 /app/tools/run_collection_scheduler.py \
  --once \
  --initial-delay-seconds 0 \
  --tracker /app/game_price_tracker \
  --database /data/game_prices.db \
  --output-dir /data/collection-snapshots \
  --lock-file /data/.collection-scheduler.lock
```

## 자동 백업

`backup-scheduler`는 기본적으로 서비스 시작 5분 후 첫 백업을 만들고 이후 하루마다
SQLite online backup, integrity check, 카탈로그 schema 검증을 수행한다. 백업 파일은
Docker volume이 아니라 프로젝트의 `backups/`에 저장되므로 컨테이너를 다시 만들어도
유지된다. 기본 보관 기간은 14일이다.

```dotenv
BACKUP_INTERVAL_SECONDS=86400
BACKUP_INITIAL_DELAY_SECONDS=300
BACKUP_RETENTION_DAYS=14
```

백업 상태와 최근 파일명은 관리자 운영 상태에 표시된다. 실제 파일과 worker 로그는
다음 명령으로 확인한다.

```bash
ls -lh backups
sudo /usr/local/bin/docker-compose -f compose.synology.yml logs --tail 100 backup-scheduler
```

복구 가능성은 파일 생성만으로 보장되지 않는다. 첫 자동 백업이 만들어진 뒤 아래
검증 명령을 실행하고, 정기적으로 새 경로 복원 리허설을 수행한다.

```bash
sudo docker run --rm \
  -v "$(pwd)/backups:/backups:ro" \
  compgameprice_api:latest \
  python3 /app/tools/database_backup.py verify \
  --backup /backups/백업파일.db
```

## 영속 데이터

Compose의 `game-price-data` volume에는 다음 핵심 파일이 함께 저장된다.

- `/data/game_prices.db`: 사용자, 가격 이력, 수집·알림·감사 기록
- `/data/game_catalog.json`: canonical Game과 Store 상품 연결
- `/data/collection-scheduler-status.json`: 자동 수집 상태
- `/data/backup-scheduler-status.json`: 자동 백업 상태

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

### Synology legacy Docker

처음 이미지를 만들 때 bridge DNS가 동작하지 않으면 build에만 host network를 사용한다.

소스와 `.env` 준비가 끝난 뒤에는 아래 스크립트 하나로 Compose 검증, 기존 데이터
백업, API/Web 빌드, volume을 보존한 컨테이너 재생성 및 health check를 수행할 수 있다.

```bash
chmod +x deploy/deploy-synology.sh
./deploy/deploy-synology.sh
```

스크립트는 `docker-compose down`이나 volume 삭제를 실행하지 않는다. SMTP 설정이
비어 있으면 경고한 뒤 배포는 계속하며, 이메일은 설정이 완료될 때까지 outbox에서
대기한다.

배포 후 `dealquest92@gmail.com`으로 일반 회원가입을 완료한 다음에만 해당 계정을
관리자로 승격한다. 주소를 만들 수 없어 다른 Gmail 주소를 사용했다면 아래 이메일도
실제 주소로 바꾼다.

```bash
sudo docker exec compgameprice_api_1 \
  python3 /app/tools/set_user_role.py \
  --database /data/game_prices.db \
  --email dealquest92@gmail.com \
  --role ADMIN
```

```bash
sudo docker build --network host -f deploy/Dockerfile.api -t compgameprice_api .
sudo docker build --network host -f deploy/Dockerfile.web -t compgameprice_web .
sudo docker build -f deploy/Dockerfile.web.synology -t compgameprice_web_synology .
```

실행과 확인 명령은 다음과 같다.

```bash
sudo /usr/local/bin/docker-compose -f compose.synology.yml up -d --no-build
sudo /usr/local/bin/docker-compose -f compose.synology.yml ps
curl -i http://127.0.0.1:8088/health
```

DSM reverse proxy의 source가 다른 Web Station portal과 충돌하면 기존 규칙을 삭제하지
말고 별도 HTTPS 포트를 사용한다. 현재 검증된 예시는 외부 `8443`에서 내부
`127.0.0.1:8088`로 전달하는 구성이다. Synology DDNS 서브도메인은 기본 도메인
인증서로 보호되지 않으므로 `*.DDNS_HOSTNAME`이 SAN에 포함된 wildcard 인증서를
해당 reverse proxy 서비스에 지정한다.

Compose 종료 시 `-v`를 사용하지 않는다. 다음 명령은 사용자, 알림, 가격 이력이
저장된 volume까지 삭제한다.

```bash
# 사용 금지
sudo /usr/local/bin/docker-compose -f compose.synology.yml down -v
```

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
