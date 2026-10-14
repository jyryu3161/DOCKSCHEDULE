#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${CONFIRM_RESTORE:-}" != "yes" ] || [ "$#" != 1 ]; then
    echo 'This replaces the current database. Use CONFIRM_RESTORE=yes scripts/restore.sh /absolute/backup/path' >&2
    exit 1
fi
backup_path=$(realpath "$1")
test -f "$backup_path/database.dump"
test -f "$backup_path/storage.tar.gz"
docker compose stop scheduler api web
# Preserve current artifacts until the restored service has been checked.
previous_path="storage.before-restore-$(date +%Y%m%d-%H%M%S)"
mv storage "$previous_path"
mkdir storage
tar -xzf "$backup_path/storage.tar.gz" -C storage
docker compose exec -T db pg_restore -U dockschedule -d dockschedule --clean --if-exists --exit-on-error < "$backup_path/database.dump"
docker compose up -d
printf 'Restored. Previous artifacts retained at %s\n' "$previous_path"
