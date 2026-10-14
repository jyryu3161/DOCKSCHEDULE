#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
backup_path=${1:-".backups/$(date +%Y%m%d-%H%M%S)"}
mkdir -p "$backup_path"
chmod 700 "$backup_path"
backup_path=$(realpath "$backup_path")
trap 'docker compose start api scheduler >/dev/null' EXIT
docker compose stop scheduler api >/dev/null
docker compose exec -T db pg_dump -U dockschedule -d dockschedule -Fc > "$backup_path/database.dump"
tar -czf "$backup_path/storage.tar.gz" -C storage .
cp .env "$backup_path/deployment.env"
chmod 600 "$backup_path"/*
printf 'Backup saved: %s\n' "$backup_path"
