#!/usr/bin/env bash
# ============================================================================
#  VPS'ni bir martalik tayyorlash (Ubuntu/Debian). root sifatida ishlatiladi.
# ----------------------------------------------------------------------------
#      ssh root@167.86.122.56
#      curl -fsSL https://raw.githubusercontent.com/akbarrashidov/speaking/main/scripts/server-setup.sh -o setup.sh
#      bash setup.sh
#
#  Nima qiladi:
#    * tizimni yangilaydi, Docker Engine + Compose plugin o'rnatadi;
#    * `deploy` foydalanuvchisini yaratadi (root'ning SSH kalitlari bilan);
#    * ufw: faqat 22/80/443; fail2ban; avtomatik xavfsizlik yangilanishlari;
#    * RAM 4GB'dan kam bo'lsa swap qo'shadi (npm build OOM bo'lmasin);
#    * repo'ni /opt/speaking ga klon qiladi.
#
#  Skript idempotent — qayta ishga tushirsa ham xavfsiz.
# ============================================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/akbarrashidov/speaking.git}"
APP_DIR="${APP_DIR:-/opt/speaking}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "XATO: root sifatida ishga tushiring (sudo -i)." >&2; exit 1; }

log "Tizim yangilanmoqda"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq ca-certificates curl git ufw fail2ban unattended-upgrades gnupg

log "Docker Engine + Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker --version && docker compose version

log "Swap (RAM 4GB'dan kam bo'lsa)"
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$RAM_MB" -lt 4000 ] && [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "2GB swap qo'shildi (RAM: ${RAM_MB}MB)."
else
  echo "Swap kerak emas yoki allaqachon bor (RAM: ${RAM_MB}MB)."
fi

log "Deploy foydalanuvchisi: $DEPLOY_USER"
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
# root'ning SSH kalitlari bilan kiriladi — parol bilan emas.
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
  install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
    /root/.ssh/authorized_keys "/home/$DEPLOY_USER/.ssh/authorized_keys"
else
  touch "/home/$DEPLOY_USER/.ssh/authorized_keys"
  chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
  chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"
  echo "OGOHLANTIRISH: /root/.ssh/authorized_keys topilmadi."
  echo "  Kalitni qo'lda qo'shing: /home/$DEPLOY_USER/.ssh/authorized_keys"
fi

log "Firewall (ufw)"
# Tartib muhim: SSH birinchi ochiladi, aks holda o'zimizni qulflab qo'yamiz.
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw default deny incoming
ufw default allow outgoing
ufw --force enable
ufw status verbose

log "fail2ban + avtomatik yangilanishlar"
systemctl enable --now fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades || true

log "Repo: $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  echo "Allaqachon klon qilingan."
else
  git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

cat <<TEXT

============================================================================
 Server tayyor.

 KEYINGI QADAMLAR (deploy foydalanuvchisi sifatida):

   su - $DEPLOY_USER
   cd $APP_DIR
   cp .env.production.example .env
   nano .env            # sirlarni to'ldiring (openssl rand -hex 48)
   bash scripts/deploy.sh

 Keyin brauzerda:  http://$(curl -fsS4 ifconfig.me 2>/dev/null || echo SERVER_IP)/

 DIQQAT: HTTP rejimida mikrofon ishlamaydi. Domen qo'shgach:
   bash scripts/enable-https.sh domen.uz admin@domen.uz
============================================================================
TEXT
