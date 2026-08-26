# AI Speaking Practice Platformasi

Ingliz tili o'rganuvchilar (o'zbek auditoriyasi) uchun speaking amaliyot platformasi —
**veb ilova**. O'quvchi email va parol bilan kiradi, Gemini Live API orqali AI bilan
real vaqtda gapiradi; suhbatlar grammatik mavzular atrofida quriladi.

Implementatsiya `speaking-platform-tz-uz.md` TZ hujjatiga muvofiq.

---

## Tez ishga tushirish

```bash
cp .env.example .env
# .env ni to'ldiring: JWT_SECRET, GEMINI_API_KEY, ANALYSIS_API_KEY
docker compose up --build
```

Ochiladi:

| Manzil | Nima |
|---|---|
| http://localhost:9100 | Veb ilova |
| http://localhost:9100/admin/ | Django admin (kontent review) |
| http://localhost:9100/healthz | Salomatlik tekshiruvi |

Admin foydalanuvchi yaratish:

```bash
docker compose exec web python manage.py createsuperuser
# email va parol so'raladi
```

Seed kontent (`SEED_CONTENT=1` bo'lsa avtomatik yuklanadi):

```bash
docker compose exec web python manage.py seed_content
```

Bu 25 ta grammatik mavzu, 250 ta tasdiqlangan savol, materiallar va chunklarni
yuklaydi. Komanda idempotent — qayta ishga tushirsa dublikat qilmaydi.

**Darajalar yo'q.** Kontentda faqat grammatik mavzular bor: har mavzu bitta
strukturani mashq qildiradi. "Daraja" suhbatning o'zida yashaydi — AI o'quvchi
qanday gapirsa, shunday gapiradi (§`practice/adaptive.py`, `register` 0..4).
Shuning uchun har mavzu har qanday o'quvchiga ochiq: savol o'zgarmaydi, unga
javob berish tili o'zgaradi.

Rejim mavzu darajasida tanlanadi (`session_mode`); bo'sh bo'lsa
`adaptive_conversation` ishlatiladi. `repeat_drill`, `speed_drill` va
`free_conversation` hali qurilmagan.

---

## Kirish va mikrofon

Foydalanuvchi **email + parol** bilan ro'yxatdan o'tadi. Server qisqa muddatli JWT
beradi (`JWT_TTL_SECONDS`, standart 1 soat); ilova uni `localStorage` da saqlaydi va
muddati tugashiga yaqin `/api/auth/refresh` orqali jimgina yangilaydi.

| Endpoint | Nima qiladi |
|---|---|
| `POST /api/auth/register` | email + parol → yangi akkaunt va JWT |
| `POST /api/auth/login` | email + parol → JWT |
| `POST /api/auth/refresh` | amaldagi JWT'ni yangisiga almashtiradi |

Parolni tanlashga qarshi kirish endpointlari IP bo'yicha alohida cheklanadi
(`THROTTLE_AUTH`, standart `10/min`). Noto'g'ri parol va mavjud bo'lmagan email
bir xil javob qaytaradi — email ro'yxatdan o'tganini bilib bo'lmaydi.

**Mikrofon xavfsiz kontekst talab qiladi.** Kompyuterda `http://localhost:9100`
o'zi xavfsiz hisoblanadi, shuning uchun qo'shimcha sozlash kerak emas. Telefondan
lokal IP orqali kirilganda brauzer mikrofonni bermaydi — vaqtinchalik HTTPS manzil
oling:

```bash
bash scripts/dev-https.sh
```

Skript `https://<random>.trycloudflare.com` manzilini chiqaradi. URL har ishga
tushirishda yangi bo'ladi, lekin `.env` dagi `DJANGO_ALLOWED_HOSTS` va
`CSRF_TRUSTED_ORIGINS` `.trycloudflare.com` ni qamrab olgani uchun ularni
tahrirlash kerak emas.

> Ishlab chiqarishda: doimiy domen + haqiqiy sertifikat, `DJANGO_ALLOWED_HOSTS`
> ni aniq domen bilan cheklang va `tunnel` servisini ishlatmang.

### Gemini Live modeli

Live modellar tez o'zgaradi. Kalitingizga qaysi biri ochiqligini tekshirish:

```bash
docker compose exec web python -c "
import os, httpx
r = httpx.get('https://generativelanguage.googleapis.com/v1beta/models',
              params={'key': os.environ['GEMINI_API_KEY'], 'pageSize': 200})
for m in r.json()['models']:
    if 'bidiGenerateContent' in m.get('supportedGenerationMethods', []):
        print(m['name'])"
```

Natijani `.env` dagi `GEMINI_LIVE_MODEL` ga yozing (`models/` prefiksisiz).

---

## Arxitektura

```
Veb ilova (React + Vite)
   │  REST (JWT)              WSS (audio)
   ▼                             ▼
nginx ──────────────────► Django + Channels (Daphne)
                              │        │
                              │        └──► Gemini Live API (server-side proxy)
                              │             faqat GAPIRADI va ESHITADI
                              │             API key clientga HECH QACHON bermaydi
                              ├──► Coach LLM     (arzon matn modeli — TIZIMNING MIYASI)
                              ├──► PostgreSQL 16 (kontent, sessiyalar, progress)
                              ├──► Redis         (sessiya holati, transkript buferi)
                              └──► Celery worker (post-session tahlil pipeline'i)
```

### Ovoz va miya ajratilgan

Live API audio tokeni qimmat ($12/1M chiqish), matn modeli esa arzon. Shuning
uchun Live modeliga **hech qanday qaror topshirilmagan** — u tool ham
chaqirmaydi, javobni ham baholamaydi. Har o'quvchi javobidan keyin:

```
O'quvchi gapiradi
   └─► Live: transkripsiya + qisqa tabiiy tasdiq ("Mm-hmm.")   ← darhol
          └─► Coach LLM (PARALLEL, kritik yo'lda emas)
                 verdict · grammatik xatolar · podkaska matni ·
                 dinamik savol · ohang
                    └─► state.py deterministik qaror qabul qiladi
                           └─► Live'ga [DIRECTOR] ko'rsatmasi
```

**Coach nima deyishni yozadi, `state.py` nima bo'lishini hal qiladi.** Shuning
uchun LLM sessiya oqimini hech qachon buzib yubora olmaydi, coach kechiksa ham
suhbat to'xtamaydi (deterministik fallback ishlaydi).

| Modul | Vazifasi | Narxi |
|---|---|---|
| `practice/coach.py` | Baholash, xato topish, podkaska, dinamik savol | ~$0.005/sessiya |
| `practice/state.py` | Tarmoqlanish qarorlari | tekin (sof Python) |
| `practice/adaptive.py` | Suhbat registri (o'quvchiga moslashish) va ohang | tekin (sof Python) |
| `practice/hints.py` | Podkaska zinapoyasi | tekin (sof Python) |
| `practice/cost.py` | Har sessiyaning aniq narxi | tekin |
| `progress/report.py` | Sessiyalararo naqshlar | SQL + 1 keshlangan chaqiruv |

### Nima uchun arzon

- **Mikrofon darvozasi** — audio faqat o'quvchi gapirayotganda oqadi (300 ms
  prefiks buferi bilan). Jimlik va AI gapirayotgan vaqt umuman to'lanmaydi.
- **`audioStreamEnd`** — client jimlikni sezsa server o'z taymerini kutmaydi:
  ham arzon, ham tezroq.
- **Tool yo'q** — ilgari har javob Live'da ikki marta generatsiya qilinardi.
- **`contextWindowCompression`** — uzun sessiyada kontekst cheksiz o'smaydi.
- **`sessionResumption`** — uzilishdan keyin kontekst qayta yuklanmaydi.
- **Xatolarni Python sanaydi** — LLM ularni faqat o'zbekchada izohlaydi.

Har sessiyaning haqiqiy narxi `session_metrics.cost_usd` va
`usage_breakdown` da saqlanadi, admin ro'yxatida ustun sifatida ko'rinadi.

### Repo tuzilmasi

```
backend/
  config/          Django sozlamalari, ASGI, Celery
  apps/users/      Email+parol auth, JWT, kvota
  apps/content/    Topic/Material/Question/Chunk, generatsiya, validatsiya
  apps/practice/   Sessiyalar: state machine, Gemini klienti, WS consumer, pipeline
  apps/progress/   TopicProgress, routing, ErrorLog, spaced repetition
  prompts/         Versiyalangan prompt shablonlari (DB'da emas)
  fixtures/        seed_content.json — 25 mavzu
  tests/           326 ta test
frontend/          Veb ilova (React + Vite, o'z routeri)
nginx/             Reverse proxy konfiguratsiyasi
```

### Muhim dizayn qarorlari

**Holat backendda.** Sessiya state machine'i (§4.4) Redis'da yashaydi, hech qachon
LLM promptida emas. Coach faqat `verdict` va matn bo'laklarini beradi; barcha
hisoblash, tarmoqlanish va savollar ketma-ketligi — `apps/practice/state.py`
dagi sof logika.

**Savollar bittalab beriladi.** System promptga savollar ro'yxati kirmaydi — har
savol `[DIRECTOR]` ko'rsatmasi orqali beriladi. Live modeli qaysi savol
navbatda ekanini bilmaydi, shuning uchun oldinga sakray olmaydi.

**Savollar gibrid.** Bank savoli — o'lchanadigan element, har doim so'zma-so'z
beriladi. Coach yozgan savol esa ko'prik: o'quvchining javobiga bog'lanadi va
target strukturani majburlaydi. Har generatsiya savol aytilishidan oldin
`content/validators.py` da tekshiriladi (yes/no emasmi, registrga mosmi,
strukturani majburlaydimi) va o'tganlari bankka `draft` bo'lib qaytadi.

**Erkin suhbatda savolni backend beradi.** Coach har navbatda keyingi savolni
yozadi, u tekshiruvdan o'tadi va ko'rsatmaga so'zma-so'z qo'yiladi. Coach
shuningdek o'quvchi javobida qaysi maqsad-savollar yopilganini qaytaradi
(`covered_goal_ids`) — bitta to'liq javob uchtasini birdan yopishi mumkin va
yopilgani boshqa so'ralmaydi.

**Rejimlar pluggable.** `ModeStrategy` (strategy pattern): MVP'da `anticipation_drill`
(A0/A1/A2, to'liq retry → model javob sikli) va `guided_conversation` (B1/B2, suhbat
oqimi buzilmaydi). Qolgan rejimlar `STRATEGIES` lug'atiga qo'shiladi.

**Prompt versiyalangan.** `prompts/` papkasidagi fayllar; har sessiyada
`PROMPT_VERSION` sessiya yozuviga log qilinadi.

---

## Lokal ishlab chiqish (Docker'siz)

```bash
# Backend
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r backend/requirements-dev.txt
cd backend
python manage.py migrate
python manage.py seed_content
python manage.py runserver          # yoki: daphne config.asgi:application

# Frontend (alohida terminal)
cd frontend && npm install && npm run dev
```

Vite dev-server `/api` va `/ws` ni `localhost:8000` ga proksilaydi.

Brauzerda `http://localhost:5173` ni oching va ro'yxatdan o'ting — qo'shimcha
sozlash kerak emas.

---

## Testlar

```bash
cd backend
python -m pytest              # 146 test, tashqi servislarsiz
python -m ruff check .
python -m ruff format --check .

cd ../frontend
npm run lint && npm run build
```

Testlar `config.settings_test` bilan ishlaydi: sqlite (xotirada), locmem cache,
in-memory channel layer, eager Celery, `fakeredis`. Postgres/Redis/tarmoq kerak emas.

Qamrov:

| Fayl | Nima tekshiriladi |
|---|---|
| `test_state_machine.py` | §4.4 barcha tarmoqlar: retry → model javob → tiklanish, 2 urinish chegarasi, guided rejim |
| `test_coach.py` | Coach JSON tahlili, ishonchsiz chiqishlar, timeout fallback |
| `test_hints.py` | Podkaska zinapoyasi, jimlik taymeri, bekor qilish |
| `test_adaptive.py` | registrning o'quvchi nutqiga moslashishi, ohang tanlash |
| `test_question_validator.py` | Real vaqtda generatsiya qilingan savollar darvozasi |
| `test_cost.py` / `test_cost_cap.py` | usage → USD, kunlik pul tomi |
| `test_progress_report.py` | Sessiyalararo naqshlar, kesh, LLM'siz yo'llar |
| `test_quota.py` | §4.9 free/premium, Toshkent kalendar kuni chegarasi, refund |
| `test_auth.py` | §4.1 ro'yxatdan o'tish, kirish, JWT muddati, brute-force chegarasi |
| `test_progress_routing.py` | §4.7 mastery, qiynalish, mavzular ketma-ketligi |
| `test_spaced_repetition.py` | §4.8 1→3→7 zinapoya, muddati kelganlar, kiritma |
| `test_pipeline.py` | §4.6 metrikalar, idempotentlik, ErrorLog |
| `test_consumer.py` | §5.1/§7.2 WS + mock Gemini, tool call ketma-ketliklari, audio relay |
| `test_content.py` | §10 sifat qoidalari, generatsiya sxemasi, seed fixture |
| `test_prompts.py` | §5.2 prompt yig'ilishi |
| `test_api.py` | §7.1 REST kontrakti |

---

## Kontent ishlab chiqish oqimi (§10)

```bash
# 1. Savollarni generatsiya qilish (draft holatida yoziladi)
python manage.py generate_topic_content --topic-id 3 --count 20

# LLM'siz sinash (tayyor JSON fayldan)
python manage.py generate_topic_content --topic-id 3 --from-file questions.json --dry-run

# 2. Admin panelda review: /admin/content/question/?status__exact=draft
#    Har savol yonida sifat tekshiruvi ko'rsatiladi (yes/no savoli, qisqa javob va h.k.)

# 3. Tashqi fayldan import
python manage.py import_questions --file questions.json --topic-id 3
python manage.py import_questions --file questions.json --validate-only
```

Sessiyalarda **faqat `approved`** savollar ishlatiladi. Mavzu nashr qilinishi uchun
kamida bitta tasdiqlangan savol va material bo'lishi shart (admin action tekshiradi).

---

## Kvota va tariflar

| Tarif | Kuniga sessiya | Sessiya davomiyligi |
|---|---|---|
| free | 1 | 5 daqiqa |
| premium | cheksiz | 15 daqiqa |

Kalendar kun **Asia/Tashkent** bo'yicha. Premium MVP'da qo'lda o'rnatiladi:
admin → Foydalanuvchilar → "Premium qilish" action.

---

## Kuzatuv (observability)

Barcha loglar `session_id` bilan strukturalangan. Muhim eventlar:

```
session_started    session_id=... user_id=... topic_id=... mode=... prompt=v1.0.0
evaluation         session_id=... q=... verdict=... attempt=... → next_question
session_finalized  session_id=... reason=... duration=...s
session_processed  session_id=... accuracy=0.80 status=mastered wpm=... latency=...ms
gemini_reconnecting / gemini_connect_failed / gemini_go_away
```

Gemini token/audio sarfi `sessions.usage` (JSONB) ustunida, pulga aylantirilgan
qiymati esa `session_metrics.cost_usd` va `usage_breakdown` da saqlanadi.

Coach va moslashuv eventlari:

```
evaluation      session_id=... q=... verdict=... coach_ok=... coach_ms=... → next_question
hint            session_id=... rung=2 kind=opener stuck=0
register        session_id=... 2 → 3 accuracy=0.90 fluency=3.5 stuck=0
goals_covered   session_id=... ids=[12, 14] remaining=6
session_cost    session_id=... usd=0.03412 live_usd=... llm_usd=... audio_in_s=...
generated_question_rejected  session_id=... "Do you like it?" ['yes/no savoli']
coach_budget_exhausted / coach_failed
```

---

## MVP'ga kirmagan (TZ §1.3 bo'yicha ataylab)

A0/A2/B2 rejimlari (strategiya interfeysi tayyor), placement test, to'lov
integratsiyasi, pronunciation scoring, 4/3/2 va retelling mashqlari.
