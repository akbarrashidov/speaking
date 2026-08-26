#!/usr/bin/env bash
# Telefonda sinash uchun vaqtinchalik HTTPS manzil beradi.
#
#   bash scripts/dev-https.sh
#
# Nega kerak: mikrofon (getUserMedia) faqat xavfsiz kontekstda ishlaydi.
# Kompyuterda `http://localhost:9100` o'zi xavfsiz hisoblanadi, lekin telefondan
# lokal IP orqali kirilganda brauzer mikrofonni bermaydi — shuning uchun tunnel.
#
# Cloudflare quick tunnel URL'i har ishga tushirishda YANGI bo'ladi.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "XATO: .env topilmadi. 'cp .env.example .env' qiling va kalitlarni to'ldiring." >&2
  exit 1
fi

if [ -z "$(docker compose ps -q tunnel 2>/dev/null)" ]; then
  echo "Tunnel ko'tarilmoqda..."
  docker compose --profile dev up -d tunnel >/dev/null
fi

echo "URL kutilmoqda..."
URL=""
for _ in $(seq 1 30); do
  URL=$(docker compose logs tunnel 2>&1 | grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" | tail -1 || true)
  [ -n "$URL" ] && break
  sleep 2
done

if [ -z "$URL" ]; then
  echo "XATO: tunnel URL'i topilmadi. 'docker compose logs tunnel' ni tekshiring." >&2
  exit 1
fi

CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/healthz" || echo "000")
if [ "$CODE" != "200" ]; then
  echo "OGOHLANTIRISH: $URL/healthz -> HTTP $CODE (stack ko'tarilganini tekshiring)" >&2
fi

cat <<EOF

Ilova manzili: $URL

Shu manzilni telefon brauzerida oching. .env dagi DJANGO_ALLOWED_HOSTS va
CSRF_TRUSTED_ORIGINS trycloudflare.com ni qamrab olgani uchun qo'shimcha
sozlash kerak emas.

Tunnelni to'xtatish:
  docker compose stop tunnel
EOF
