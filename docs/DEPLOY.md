# Serverga qo'yish (167.86.122.56 — Cloud VPS 4)

## GitHub yetarli — GitLab'ga o'tish shart emas

Repo allaqachon `github.com/akbarrashidov/speaking` da. GitHub Actions ham
bepul, ham kuchli. `.gitlab-ci.yml` fayli joyida qoldi (zarar qilmaydi), lekin
ishlaydigani `.github/workflows/ci-cd.yml`.

Sxema: **siz `main`ga push qilasiz → GitHub lint+test+build qiladi → hammasi
yashil bo'lsa SSH orqali serverga kirib `deploy.sh` ni ishga tushiradi.**
Image'lar serverning o'zida yig'iladi, registry kerak emas.

---

## ⚠️ Eng muhim ogohlantirish: mikrofon HTTPS talab qiladi

Brauzerning `getUserMedia()` API'si **faqat xavfsiz kontekstda** ishlaydi:
`https://` yoki `localhost`. `http://167.86.122.56` — xavfsiz emas.

Ya'ni IP orqali kirganda: admin panel, ro'yxatdan o'tish, kontent ko'rish —
hammasi ishlaydi, **lekin ovoz sessiyasi ochilmaydi**. Bu loyihaning asosiy
funksiyasi bo'lgani uchun domen olish amalda majburiy.

Domen olgach bitta buyruq bilan HTTPS yoqiladi — pastda 6-qadam.

---

## 1-qadam. Serverni tayyorlash (bir marta)

Windows'dan PowerShell'da:

```powershell
ssh root@167.86.122.56
```

Serverda:

```bash
curl -fsSL https://raw.githubusercontent.com/akbarrashidov/speaking/main/scripts/server-setup.sh -o setup.sh
bash setup.sh
```

Skript: tizimni yangilaydi, Docker + Compose o'rnatadi, `deploy`
foydalanuvchisini yaratadi, ufw (22/80/443) va fail2ban'ni yoqadi, kerak bo'lsa
swap qo'shadi, repo'ni `/opt/speaking` ga klon qiladi.

> **Parol haqida.** Serverga parol bilan kirasiz. O'sha parol endi suhbat
> tarixida qolgani uchun uni almashtiring: serverda `passwd`. Undan ham yaxshisi
> — SSH kalitiga o'ting (2-qadam) va parol bilan kirishni butunlay yoping:
>
> ```bash
> sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
> sudo systemctl restart ssh
> ```
>
> Buni **faqat kalit bilan kira olishingizga ishonch hosil qilgandan keyin**
> qiling, aks holda o'zingizni tashqarida qoldirasiz.

---

## 2-qadam. SSH kalitlari

**A) O'zingiz uchun** (Windows PowerShell'da, hali kalitingiz bo'lmasa):

```powershell
ssh-keygen -t ed25519 -C "akbar-laptop"
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@167.86.122.56 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

Keyin `server-setup.sh` ni qayta ishga tushiring — u kalitni `deploy`
foydalanuvchisiga ham ko'chiradi. Tekshiring:

```powershell
ssh deploy@167.86.122.56 "docker ps"
```

**B) GitHub Actions uchun alohida kalit** (parolsiz bo'lishi shart):

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\speaking_deploy" -N '""' -C "github-actions"
type $env:USERPROFILE\.ssh\speaking_deploy.pub | ssh deploy@167.86.122.56 "cat >> ~/.ssh/authorized_keys"
```

Alohida kalit kerak: CI buzilsa yoki secret sizib ketsa, faqat shu kalitni
bekor qilasiz — shaxsiy kalitingizga tegmasdan.

---

## 3-qadam. `.env` ni to'ldirish

```bash
ssh deploy@167.86.122.56
cd /opt/speaking
cp .env.production.example .env
nano .env
```

Albatta o'zgartiriladigan qatorlar:

| Kalit | Qiymat |
|---|---|
| `DJANGO_SECRET_KEY` | `openssl rand -hex 48` natijasi |
| `JWT_SECRET` | **boshqa** `openssl rand -hex 48` natijasi |
| `POSTGRES_PASSWORD` | kuchli parol |
| `GEMINI_API_KEY` | Google AI Studio kaliti |
| `ANALYSIS_API_KEY` | Fireworks.ai (yoki boshqa OpenAI-mos) kaliti |

`.env` git'ga **hech qachon** tushmaydi — `.gitignore` uni to'sib turadi.
Shuning uchun u serverda qo'lda yaratiladi va o'sha yerda qoladi.

---

## 4-qadam. Birinchi deploy

```bash
cd /opt/speaking
bash scripts/deploy.sh
```

Birinchi marta 3–6 daqiqa (image'lar yig'iladi). Skript oxirida `healthz -> 200`
chiqsa tayyor. Brauzerda: **http://167.86.122.56/**

Admin yaratish:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
docker compose exec web python manage.py createsuperuser
```

Kontent yuklangandan keyin `.env` da `SEED_CONTENT=0` qiling — har deploy'da
seed qayta yugurmasin.

---

## 5-qadam. GitHub Actions'ni ulash

GitHub'da: **Settings → Secrets and variables → Actions → New repository secret**

| Nomi | Qiymati |
|---|---|
| `SSH_HOST` | `167.86.122.56` |
| `SSH_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | `speaking_deploy` faylining **to'liq matni** (`-----BEGIN` dan `-----END` gacha) |
| `SSH_KNOWN_HOSTS` | `ssh-keyscan -H 167.86.122.56` natijasi |
| `APP_DIR` | `/opt/speaking` (ixtiyoriy) |

Qiymatlarni clipboard'ga olish (PowerShell):

```powershell
Get-Content $env:USERPROFILE\.ssh\speaking_deploy | Set-Clipboard
ssh-keyscan -H 167.86.122.56 | Set-Clipboard
```

Shundan keyin har `git push origin main` avtomatik deploy qiladi.

> Ixtiyoriy, lekin tavsiya: **Settings → Environments → New environment →
> `production`** yarating va o'zingizni *required reviewer* qilib qo'ying.
> Shunda har deploy tugmani bosishingizni kutadi — tasodifiy push prodni
> buzmaydi.

---

## 6-qadam. Domen va HTTPS

1. Domen sotib oling (`.uz` — ahost.uz / uzinfocom; arzonroq variant `.com`
   yoki `.app` — Namecheap, Cloudflare).
2. DNS'da **A-record**: `@ → 167.86.122.56` (xohlasangiz `www` ham).
3. Tarqalishini kuting (odatda 5–30 daqiqa). Tekshirish: `dig +short domen.uz`
4. Serverda:

```bash
cd /opt/speaking
bash scripts/enable-https.sh domen.uz sizning@email.com
```

Skript o'zi: DNS'ni tekshiradi → Let's Encrypt sertifikatini oladi → nginx
HTTPS konfigini generatsiya qiladi → `.env` ni yangilaydi (`SECURE_COOKIES=1`,
`CSRF_TRUSTED_ORIGINS`, `DJANGO_ALLOWED_HOSTS`) → stack'ni qayta ko'taradi.

Sertifikat 12 soatda bir marta avtomatik tekshiriladi va yangilanadi
(`certbot` konteyneri), nginx esa 6 soatda bir marta reload bo'ladi.

Let's Encrypt haftalik limitiga urilmaslik uchun avval sinov rejimida:

```bash
bash scripts/enable-https.sh domen.uz sizning@email.com --staging
```

Sinov sertifikatini brauzer ishonchsiz deb ko'rsatadi — bu normal. Hammasi
joyida bo'lsa `--staging` siz qayta ishga tushiring.

---

## Kundalik ishlar

Hamma buyruqlar `/opt/speaking` ichida. Avval:

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
```

| Nima | Buyruq |
|---|---|
| Holat | `docker compose ps` |
| Loglar | `docker compose logs -f web` |
| Qayta ishga tushirish | `docker compose restart web worker` |
| Qo'lda deploy | `bash scripts/deploy.sh` |
| Faqat qayta yig'ish | `bash scripts/deploy.sh --no-pull` |
| Django shell | `docker compose exec web python manage.py shell` |
| Baza zaxirasi | `bash scripts/backup-db.sh` |
| Oldingi versiyaga qaytish | `DEPLOY_REF=<commit-sha> bash scripts/deploy.sh` |

Har kunlik avtomatik zaxira (`crontab -e`, `deploy` foydalanuvchisi ostida):

```
0 3 * * * cd /opt/speaking && bash scripts/backup-db.sh >> backups/cron.log 2>&1
```

---

## Muammolar

**`healthz` 200 qaytarmayapti**

```bash
docker compose logs --tail 100 web
```

Ko'pincha `.env` da kalit yetishmaydi yoki `POSTGRES_PASSWORD` volume'dagi eski
parolga mos kelmaydi. Ikkinchi holatda bazani tozalash kerak (**barcha
ma'lumot o'chadi**): `docker compose down -v`.

**Admin panelga kirganda 403 / CSRF xatosi**

`.env` dagi `CSRF_TRUSTED_ORIGINS` brauzerdagi manzilga protokoli bilan aynan
mos kelishi kerak: HTTP'da `http://167.86.122.56`, HTTPS'da `https://domen.uz`.
HTTP rejimida `SECURE_COOKIES=0` bo'lishi shart — aks holda brauzer cookie'ni
umuman yubormaydi.

**Mikrofon ishlamayapti**

HTTPS'ga o'tganingizni tekshiring. `http://` da bu kutilgan xatti-harakat.

**Deploy `git reset --hard` da to'xtadi**

Serverda qo'lda fayl o'zgartirgansiz. `git status` bilan ko'ring; kerakli
o'zgarishni repo'ga commit qiling, keyin qayta deploy qiling.

**Sayt ochilmayapti**

```bash
sudo ufw status
docker compose ps
curl -I http://127.0.0.1/healthz
```

---

## Fayllar xaritasi

| Fayl | Vazifasi |
|---|---|
| `docker-compose.yml` | bazaviy stack (lokal ishlab chiqish) |
| `docker-compose.prod.yml` | prod qatlami: 80/443, certbot, log limitlari |
| `nginx/default.conf` | lokal dev nginx |
| `nginx/prod-http.conf` | prod, HTTPS'gacha |
| `nginx/prod-ssl.conf.template` | HTTPS shabloni (`__DOMAIN__` almashtiriladi) |
| `nginx/snippets/` | ikkala prod konfig ulaydigan umumiy qism |
| `.env.production.example` | serverdagi `.env` uchun namuna |
| `scripts/server-setup.sh` | VPS'ni bir martalik tayyorlash |
| `scripts/deploy.sh` | deploy (qo'lda ham, CI ham shuni chaqiradi) |
| `scripts/enable-https.sh` | Let's Encrypt + HTTPS'ga o'tish |
| `scripts/backup-db.sh` | PostgreSQL zaxirasi |
| `.github/workflows/ci-cd.yml` | lint → test → build → deploy |
