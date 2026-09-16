#!/usr/bin/env bash
# ============================================================================
#  Serverda deploy. Qo'lda ham, GitHub Actions ham shu skriptni chaqiradi.
# ----------------------------------------------------------------------------
#      cd /opt/speaking && bash scripts/deploy.sh          # main'ni tortadi
#      bash scripts/deploy.sh --no-pull                    # faqat qayta yig'adi
#      DEPLOY_REF=abc1234 bash scripts/deploy.sh           # aniq commit'ga
#
#  Image'lar shu serverda yig'iladi (registry ishlatilmaydi).
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"

# Ikki compose fayl doim birga: bazaviy + prod qatlami.
export COMPOSE_FILE="docker-compose.yml:docker-compose.prod.yml"
BRANCH="${DEPLOY_BRANCH:-main}"
PULL=1
[ "${1:-}" = "--no-pull" ] && PULL=0

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mXATO: %s\033[0m\n' "$*" >&2; exit 1; }

[ -f .env ] || fail ".env topilmadi. 'cp .env.production.example .env' qiling va to'ldiring."

# Prodda DEBUG yoqiq qolishi — eng ko'p uchraydigan va eng qimmat xato.
if grep -qE '^DJANGO_DEBUG=(1|true|True|yes|on)' .env; then
  fail "DJANGO_DEBUG yoqiq. .env da DJANGO_DEBUG=0 qiling."
fi
if grep -qE '^DJANGO_SECRET_KEY=(BU_YERGA|change-me|$)' .env; then
  fail "DJANGO_SECRET_KEY o'rnatilmagan. 'openssl rand -hex 48' bilan yarating."
fi

if [ "$PULL" -eq 1 ]; then
  log "Kod yangilanmoqda ($BRANCH)"
  git fetch --prune origin
  TARGET="${DEPLOY_REF:-origin/$BRANCH}"
  # `--hard`: serverda qo'lda o'zgartirilgan fayllar bo'lsa deploy tiqilib
  # qolmasin. Generatsiya qilingan fayllar (.env, nginx/prod-ssl.conf) git'da
  # kuzatilmaydi, shuning uchun ularga tegilmaydi.
  git reset --hard "$TARGET"
  git --no-pager log -1 --oneline
fi

log "Image'lar yig'ilmoqda"
docker compose build

log "Servislar ko'tarilmoqda"
docker compose up -d --remove-orphans

log "Sog'liq tekshiruvi"
# web konteyneri migratsiya + collectstatic'ni entrypoint'da bajaradi —
# birinchi ishga tushish bir necha o'n soniya olishi mumkin.
OK=0
for i in $(seq 1 40); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/healthz || echo 000)
  if [ "$CODE" = "200" ]; then OK=1; echo "healthz -> 200 (${i}-urinish)"; break; fi
  sleep 3
done

if [ "$OK" -ne 1 ]; then
  echo "--- oxirgi loglar ---" >&2
  docker compose ps >&2
  docker compose logs --tail 60 web nginx >&2
  fail "healthz javob bermadi. Yuqoridagi loglarni tekshiring."
fi

log "Eski image'lar tozalanmoqda"
docker image prune -f >/dev/null

log "Tayyor"
docker compose ps
