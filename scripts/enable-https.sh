#!/usr/bin/env bash
# ============================================================================
#  Let's Encrypt sertifikati va HTTPS'ga o'tish.
# ----------------------------------------------------------------------------
#      bash scripts/enable-https.sh domen.uz admin@domen.uz
#      bash scripts/enable-https.sh domen.uz admin@domen.uz --staging   # sinov
#
#  OLDINDAN: domenning A-record'i shu server IP'siga qaragan bo'lishi SHART.
#  Tekshirish:  dig +short domen.uz
#
#  Nega kerak: mikrofon (getUserMedia) faqat xavfsiz kontekstda ishlaydi.
#  HTTPS bo'lmasa ovoz sessiyasi umuman ochilmaydi.
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
export COMPOSE_FILE="docker-compose.yml:docker-compose.prod.yml"

DOMAIN="${1:-}"
EMAIL="${2:-}"
STAGING_FLAG=""
[ "${3:-}" = "--staging" ] && STAGING_FLAG="--staging"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mXATO: %s\033[0m\n' "$*" >&2; exit 1; }

[ -n "$DOMAIN" ] && [ -n "$EMAIL" ] || fail "Ishlatilishi: bash scripts/enable-https.sh domen.uz email@domen.uz"
[ -f .env ] || fail ".env topilmadi."

# .env dagi kalitni o'rnatadi yoki yangilaydi (bor bo'lsa almashtiradi).
set_env() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" .env; then
    # `|` ajratgich — qiymatda `/` bo'lishi mumkin (https://...).
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    printf '%s=%s\n' "$key" "$val" >> .env
  fi
}

log "DNS tekshiruvi"
SERVER_IP=$(curl -fsS4 ifconfig.me 2>/dev/null || echo "")
DNS_IP=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}' || echo "")
echo "  server: ${SERVER_IP:-aniqlanmadi}   $DOMAIN -> ${DNS_IP:-aniqlanmadi}"
if [ -n "$SERVER_IP" ] && [ -n "$DNS_IP" ] && [ "$SERVER_IP" != "$DNS_IP" ]; then
  fail "$DOMAIN shu serverga qaramayapti. A-record'ni $SERVER_IP ga yo'naltiring va DNS tarqalishini kuting."
fi
[ -n "$DNS_IP" ] || fail "$DOMAIN uchun A-record topilmadi."

log "nginx HTTP rejimida ko'tarilmoqda (ACME tekshiruvi uchun)"
set_env NGINX_CONF "prod-http.conf"
docker compose up -d nginx web
sleep 3

log "Sertifikat so'ralmoqda ($DOMAIN)"
# `--entrypoint certbot`: compose'dagi entrypoint yangilash sikli — bu yerda
# bir martalik buyruq kerak.
docker compose run --rm --entrypoint certbot certbot certonly \
  --webroot -w /var/www/certbot \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos --no-eff-email --non-interactive \
  $STAGING_FLAG \
  || fail "certbot sertifikat ololmadi. 80-port ochiqligini (ufw) va DNS'ni tekshiring."

log "nginx HTTPS konfigi generatsiya qilinmoqda"
sed "s|__DOMAIN__|${DOMAIN}|g" nginx/prod-ssl.conf.template > nginx/prod-ssl.conf

log ".env yangilanmoqda"
set_env NGINX_CONF "prod-ssl.conf"
set_env COMPOSE_PROFILES "tls"
set_env SECURE_COOKIES "1"
set_env CSRF_TRUSTED_ORIGINS "https://${DOMAIN}"
# Domenni ruxsat etilgan hostlarga qo'shamiz, IP ham qolsin.
CURRENT_HOSTS=$(grep -E '^DJANGO_ALLOWED_HOSTS=' .env | cut -d= -f2- || echo "")
case ",${CURRENT_HOSTS}," in
  *",${DOMAIN},"*) ;;
  *) set_env DJANGO_ALLOWED_HOSTS "${CURRENT_HOSTS:+${CURRENT_HOSTS},}${DOMAIN}" ;;
esac

log "Stack qayta ko'tarilmoqda (certbot yangilash sikli bilan)"
COMPOSE_PROFILES=tls docker compose up -d --remove-orphans

log "Tekshiruv"
sleep 5
CODE=$(curl -s -o /dev/null -w '%{http_code}' "https://${DOMAIN}/healthz" || echo 000)
if [ "$CODE" = "200" ]; then
  printf '\n\033[1;32mTayyor: https://%s\033[0m\n' "$DOMAIN"
  echo "Mikrofon endi ishlaydi. Sertifikat 12 soatda bir marta avtomatik yangilanadi."
else
  echo "OGOHLANTIRISH: https://${DOMAIN}/healthz -> HTTP $CODE" >&2
  docker compose logs --tail 40 nginx >&2
fi
