#!/bin/sh
set -eu

catalog_path="${GAME_PRICE_CATALOG_PATH:-/data/game_catalog.json}"
catalog_directory="$(dirname "$catalog_path")"
mkdir -p "$catalog_directory"

if [ ! -f "$catalog_path" ]; then
    cp /app/seed-data/game_catalog.json "$catalog_path"
fi

exec /app/game_price_api
