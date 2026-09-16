#!/usr/bin/env bash
# ============================================================================
#  PostgreSQL zaxira nusxasi. Oxirgi 14 kunlik saqlanadi.
# ----------------------------------------------------------------------------
#      bash scripts/backup-db.sh
#
#  Har kuni avtomatik (deploy foydalanuvchisi ostida `crontab -e`):
#      0 3 * * * cd /opt/speaking && bash scripts/backup-db.sh >> backups/cron.log 2>&1
#
#  Tiklash:
#      gunzip -c backups/speaking-2026-09-16-030000.sql.gz \
#        | docker compose exec -T postgres psql -U speaking -d speaking
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_FILE="docker-compose.yml:docker-compose.prod.yml"

BACKUP_DIR="${BACKUP_DIR:-backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

DB_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2- || echo speaking)
DB_NAME=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2- || echo speaking)
OUT="$BACKUP_DIR/speaking-$(date +%Y-%m-%d-%H%M%S).sql.gz"

# `-T`: TTY ajratilmaydi, aks holda cron ostida yiqiladi.
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$OUT"

# Bo'sh yoki yarim yozilgan fayl "zaxira bor" degan yolg'on tuyg'u bermasin.
SIZE=$(wc -c < "$OUT")
if [ "$SIZE" -lt 1000 ]; then
  rm -f "$OUT"
  echo "XATO: zaxira juda kichik ($SIZE bayt) — o'chirildi. postgres ishlayaptimi?" >&2
  exit 1
fi

find "$BACKUP_DIR" -name 'speaking-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "OK: $OUT ($(du -h "$OUT" | cut -f1))"
