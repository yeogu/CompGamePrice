#!/usr/bin/env bash
set -euo pipefail

project_directory=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
compose_binary=/usr/local/bin/docker-compose
docker_binary=/usr/local/bin/docker
compose_file="${project_directory}/compose.synology.yml"
environment_file="${project_directory}/.env"
backup_directory="${project_directory}/backups"
data_volume=compgameprice_game-price-data

if [[ ! -x "${compose_binary}" ]]; then
    echo "Synology docker-compose를 찾을 수 없습니다: ${compose_binary}" >&2
    exit 1
fi
if [[ ! -x "${docker_binary}" ]]; then
    echo "Synology Docker CLI를 찾을 수 없습니다: ${docker_binary}" >&2
    exit 1
fi
if [[ ! -f "${environment_file}" ]]; then
    echo ".env 파일이 없습니다. .env.example을 참고해 먼저 생성하세요." >&2
    exit 1
fi
if ! grep -Eq '^SMTP_HOST=.+$' "${environment_file}" ||
   ! grep -Eq '^SMTP_FROM=.+$' "${environment_file}"; then
    echo "경고: SMTP_HOST 또는 SMTP_FROM이 비어 있어 이메일은 발송 대기 상태가 됩니다." >&2
fi

cd "${project_directory}"
mkdir -p "${backup_directory}"

echo "[1/7] Compose 설정을 검증합니다."
sudo "${compose_binary}" -f "${compose_file}" config >/dev/null

echo "[2/7] 현재 SQLite DB와 카탈로그를 백업합니다."
sudo "${docker_binary}" run --rm \
    -v "${data_volume}:/data:ro" \
    -v "${backup_directory}:/backups" \
    compgameprice_api:latest \
    python3 /app/tools/database_backup.py backup \
    --database /data/game_prices.db \
    --catalog /data/game_catalog.json \
    --output-dir /backups

echo "[3/7] 방금 만든 백업의 복원 가능성을 검사합니다."
latest_backup=$(find "${backup_directory}" -maxdepth 1 -type f -name '*.db' -print | sort | tail -n 1)
if [[ -z "${latest_backup}" ]]; then
    echo "검증할 SQLite 백업을 찾을 수 없습니다." >&2
    exit 1
fi
latest_backup_name=$(basename "${latest_backup}")
sudo "${docker_binary}" run --rm \
    -v "${backup_directory}:/backups:ro" \
    compgameprice_api:latest \
    sh -c '
        cp "$1" /tmp/source-backup.db
        python3 /app/tools/database_backup.py restore \
            --backup /tmp/source-backup.db \
            --output /tmp/restore-test.db
    ' sh "/backups/${latest_backup_name}"

echo "[4/7] API 이미지를 빌드합니다."
sudo "${docker_binary}" build \
    --network host \
    -f deploy/Dockerfile.api \
    -t compgameprice_api:latest \
    .

echo "[5/7] Web 이미지를 빌드합니다."
deploy_revision=$(date -u +%Y%m%dT%H%M%SZ)
sudo "${docker_binary}" build \
    --network host \
    --build-arg "WEB_BUILD_REVISION=${deploy_revision}" \
    -f deploy/Dockerfile.web \
    -t compgameprice_web:latest \
    .
sudo "${docker_binary}" build \
    --build-arg "DEPLOY_REVISION=${deploy_revision}" \
    -f deploy/Dockerfile.web.synology \
    -t compgameprice_web_synology:latest \
    .

echo "[6/7] 기존 volume을 보존한 채 컨테이너를 다시 만듭니다."
sudo "${compose_binary}" \
    -f "${compose_file}" \
    up -d --no-build --force-recreate

echo "[7/7] 서비스 상태, API health와 Web revision을 확인합니다."
for _attempt in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8088/health >/dev/null 2>&1; then
        served_revision=$(curl -fsS http://127.0.0.1:8088/deploy-revision.txt)
        if [[ "${served_revision}" != "${deploy_revision}" ]]; then
            echo "Web revision 불일치: expected=${deploy_revision}, served=${served_revision}" >&2
            exit 1
        fi
        sudo "${compose_binary}" -f "${compose_file}" ps
        echo "배포가 완료되었습니다: revision=${deploy_revision}"
        exit 0
    fi
    sleep 2
done

sudo "${compose_binary}" -f "${compose_file}" ps
echo "배포 후 60초 안에 health check가 성공하지 않았습니다." >&2
echo "API와 web 로그를 확인하세요." >&2
exit 1
