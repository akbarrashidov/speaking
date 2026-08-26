# aiwork — agent klientini o'rnatish

Bu papkadagi narsalar **ishchi mashinaga** tushadi: siz kod yozayotgan kompyuterga
va u yerdagi loyihaga. Server tomonida hech narsa o'rnatilmaydi.

Maqsad bitta: Claude Code (yoki boshqa MCP agenti) **doska bilan gaplashsin** —
vazifani o'zi olsin, ro'yxat bo'yicha ishlasin, har bir tugagan qadamni belgilab,
ish jurnaliga yozib borsin. Shunda kompyuter o'chsa ham ish yo'qolmaydi:
keyingi safar agent aynan o'sha yozuvlardan davom etadi.

```
sizning kompyuteringiz                     server (work.ai-energy.team)
┌───────────────────────────┐              ┌──────────────────────────┐
│ Claude Code               │  HTTPS       │ MCP server  (11 asbob)   │
│  ├─ .mcp.json  ← manzil   │─────────────▶│ ↕                        │
│  ├─ AIWORK_TOKEN ← kalit  │  Bearer      │ Postgres: vazifalar,     │
│  ├─ .claude/skills/aiwork │              │ ro'yxatlar, reportlar,   │
│  └─ hook ──▶ ~/.aiwork/   │              │ faoliyat izi             │
│              journal.ndjson              └──────────────────────────┘
└───────────────────────────┘                          ▲
        (tarmoqqa chiqmaydi;                odam doskada ko'radi:
         izni agent olib ketadi)            work.ai-energy.team
```

Ikki qatlam, ikki xil narsa. **Hisobot** — agentning talqini: nima qildi va
nega. **Faoliyat izi** — fakt: fayl o'zgardi. Biri ikkinchisining o'rnini
bosmaydi va ikkinchisidan chiqarilmaydi: hook nima uchun qilinganini bilmaydi,
hisobot esa har doim yozilmaydi — doskaning aynan shu bo'shliqni ko'rsatishi
uchun iz kerak.

---

## 1. Nima kerak

| Nima | Izoh |
|---|---|
| **Claude Code** | `npm i -g @anthropic-ai/claude-code` yoki desktop ilova. Codex va boshqa MCP mijozlari ham ishlaydi — pastdagi «Boshqa agentlar» ga qarang. |
| **Shaxsiy token** | Jamoa egasi yoki admin serverda chiqarib beradi (2-bo'lim). Har bir odamga o'ziniki; bo'lishib olinmaydi. |
| **Loyiha papkasi** | Agent ishlaydigan git-repozitoriy. Fayllar shuning ichiga tushadi. |
| **Doskada akkaunt** | `work.ai-energy.team` ga taklif bo'yicha kirilgan bo'lishi kerak. Token o'sha odam nomidan ishlaydi. |

Serverga SSH, Docker va ma'lumotlar bazasi **kerak emas**.

---

## 2. Token olish

Tokenni **jamoa egasi** serverda chiqaradi va odamga xavfsiz kanal orqali beradi
(token bir marta ko'rsatiladi, bazada faqat SHA-256 saqlanadi):

```bash
cd /opt/ai-energy/work-app
docker compose exec backend python -m app.cli issue-cli-token \
    odam@example.com  jamoa-slug  "laptop"
```

Uchala argument majburiy: **pochta**, **jamoa slug'i**, **belgi** (qaysi mashina
uchun — keyin ro'yxatda shu ko'rinadi).

Yordamchi buyruqlar:

```bash
docker compose exec backend python -m app.cli list-teams          # slug'lar
docker compose exec backend python -m app.cli list-cli-tokens     # amaldagi tokenlar
docker compose exec backend python -m app.cli revoke-cli-token <session-id>
```

> **Token — shaxsiy kalit.** U bilan doskaga sizning nomingizdan yoziladi.
> Repozitoriyga, chatga, skrinshotga tushmasin. Shubha bo'lsa — darhol
> `revoke-cli-token` va yangisini oling.

---

## 3. Tokenni muhitga qo'yish

Token faylda emas, **muhit o'zgaruvchisida** yashaydi: `.mcp.json` da faqat
`${AIWORK_TOKEN}` yozuvi turadi, shuning uchun konfiguratsiyani repoga
qo'ysangiz ham kalit u yerga tushmaydi.

**Windows (PowerShell).** Doimiy qilib:

```powershell
setx AIWORK_TOKEN "bu-yerga-token"
```

`setx` **yangi** terminallarga ta'sir qiladi — ochiq turgan oynani yoping va
qaytadan oching. Faqat shu seans uchun: `$env:AIWORK_TOKEN = "..."`.

**macOS / Linux.** `~/.zshrc` yoki `~/.bashrc` ga:

```bash
export AIWORK_TOKEN="bu-yerga-token"
```

so'ng `source ~/.zshrc` yoki terminalni qayta oching.

Tekshirish: `echo $env:AIWORK_TOKEN` (PowerShell) / `echo $AIWORK_TOKEN` (bash) —
token ko'rinishi kerak.

---

## 4. Fayllarni loyihaga o'rnatish

Zip'ni oching va loyiha papkasini ko'rsating.

**Windows:**

```powershell
cd aiwork-client
.\install.ps1 -Target C:\projects\mening-loyiham
```

**macOS / Linux:**

```bash
cd aiwork-client
bash install.sh ~/projects/mening-loyiham
```

Skript nima qiladi:

| Fayl | Qayerga tushadi | Agar mavjud bo'lsa |
|---|---|---|
| `.mcp.json` | `<loyiha>/.mcp.json` | tegilmaydi, farqi ko'rsatiladi |
| `skills/aiwork/SKILL.md` | `<loyiha>/.claude/skills/aiwork/SKILL.md` | ustiga yoziladi (bu — qoidalarning yagona manbasi) |
| `CLAUDE.md.snippet` | `<loyiha>/CLAUDE.md` oxiriga | allaqachon bo'lsa qo'shilmaydi |
| `hooks/aiwork-pulse` | `~/.aiwork/aiwork-pulse` | ustiga yoziladi |
| — | `~/.claude/settings.json` ning `hooks.PostToolUse` iga bitta yozuv | **qo'shiladi**, ustiga yozilmaydi; allaqachon bor bo'lsa takrorlanmaydi |
| — | `~/.aiwork/projects` ga loyiha yo'li | takrorlanmaydi |

`settings.json` — sizning faylingiz: unda model, tema, boshqa hook'lar turadi.
O'rnatgich uni o'qiydi, bitta yozuv qo'shadi va qaytaradi. Faoliyat izi kerak
bo'lmasa: `install.ps1 -NoHook` yoki `AIWORK_NO_HOOK=1 bash install.sh ...`.

**Hook global ro'yxatga olinadi**, ya'ni mashinadagi har qanday loyihada
chaqiriladi. Shuning uchun `~/.aiwork/projects` ro'yxati bor: hook faqat shu
papkalar ichidagi ishni yozadi. Usiz begona repozitoriyning fayl yo'llari
jamoaning bazasiga tushardi.

**Sozlama ochilishda o'qiladi** — o'rnatgandan keyin Claude Code'ni qayta ishga
tushiring.

Qo'lda qilmoqchi bo'lsangiz — shu ko'chirishlarning o'zi, boshqa hech narsa yo'q.

**Loyiha slug'ini to'g'rilang.** `.mcp.json` ichida:

```json
"X-Aiwork-Project": "umumiy"
```

`umumiy` o'rniga shu repozitoriyga mos loyiha slug'ini yozing (doskada
«Loyihalar» bo'limida ko'rinadi). Sarlavhani butunlay olib tashlasangiz ham
bo'ladi — u holda agent siz ko'ra oladigan **barcha** loyihalar bo'yicha
ishlaydi va har javobda ogohlantirish qaytaradi.

---

## 5. Ulanishni tekshirish

Avval — Claude Code'siz, toza tekshiruv:

```powershell
.\check.ps1                     # Windows
```
```bash
bash check.sh                   # macOS / Linux
```

Skript hech narsani o'zgartirmaydi: ulanadi, asboblar ro'yxatini, doska
ustunlarini, sizga tegishli vazifalarni va faoliyat izining holatini ko'rsatadi.
Kutilgan natija — o'n bitta asbob nomi, ustunlar oqimi va hook «ro'yxatda» deb
turishi.

Hook'ning o'zini alohida sinash (tarmoq kerak emas):

```bash
echo '{"session_id":"test","tool_name":"Edit","tool_input":{"file_path":"a.py"},"cwd":"'"$PWD"'"}' \
  | python ~/.aiwork/aiwork-pulse
cat ~/.aiwork/journal.ndjson        # oxirgi qator paydo bo'lishi kerak
```

Buzuq JSON bersangiz ham `exit 0` bo'lishi kerak: hook hech qachon agent
oqimini to'xtatmaydi.

So'ng Claude Code ichida:

```
claude            # loyiha papkasida
/mcp              # ro'yxatda "aiwork" ✓ connected bo'lishi kerak
```

---

## 6. Birinchi ish oqimi

**Odam doskada** (`work.ai-energy.team`) vazifa yaratadi. Matnni erkin yozib
«AI bilan» tugmasini bossa, model sarlavha, muddat va **bajarish ro'yxatini**
o'zi tuzib beradi — odam ortiqchasini olib tashlab, kartochkani yaratadi.

**Agentga ish berishning ikki yo'li bor.**

*Birinchisi — talon.* Kartochkada «Agentga berish» tugmasi kod chiqaradi
(`AIW-7F3K`). Claude Code'ga shunchaki yozasiz:

```
aiwork AIW-7F3K
```

Talon seansni o'zi ochadi va vazifani ishga oladi.

*Ikkinchisi — agent o'zi tanlaydi:*

```
aiwork bo'yicha menga tegishli vazifani ol va boshla
```

Agent `start_session` → `next_assignment` → `claim_task` ni o'zi chaqiradi.

**Keyin nima bo'ladi.** Agent kartochkadagi ro'yxat bo'yicha ketadi: birinchi
belgilanmagan punktni oladi, bajaradi, **darhol** belgilaydi va nima qilganini
yozib qo'yadi. Doskada bu jonli ko'rinadi: progress chizig'i, punktlardagi
belgilar va agent jurnalidagi yozuvlar.

**Ish tugaganda** agent `finish_task` chaqiradi — vazifa `awaiting_review`
bayrog'ini oladi, **lekin ustunini o'zgartirmaydi**. Kartochkani «Tayyor» ga
ko'chirish faqat odamning ishi.

Chaqiruv suhbat oxirini kutmaydi: ish tugagan payt chaqiriladi va keyingi
vazifa faqat shundan keyin olinadi — bir vaqtda bitta vazifa ochiq turadi.
Doskada vazifasi yo'q ish qilingan bo'lsa (masalan build buzilgan edi), agent
uni alohida `report_unplanned` bilan yozadi — u «Rejadan tashqari» ustuniga
tushadi va asosiy oqimga aralashmaydi.

**Kompyuter o'chib qolsa** — hech narsa yo'qolmaydi. Keyingi safar:

```
aiwork: o'sha vazifani davom ettir
```

Agent `claim_task` ni qayta chaqiradi, javobda ro'yxat (belgilari bilan) va
oldingi reportlar keladi va u aynan to'xtagan joyidan davom etadi.

---

## 7. Faoliyat izi — ish bo'lgani, hisobot yo'qligi

> Sabablarsiz, faqat qadamlar kerak bo'lsa — `ISHLATISH.md`.

Ko'rsatma ehtimollikni oshiradi, kafolat bermaydi: agent «keyinroq yozaman» deb
oxirigacha yetib bormasligi mumkin. Hook esa deterministik — uni Claude Code
runtime majburan chaqiradi, model qarori qatnashmaydi.

**Hook hisobot yozmaydi.** U har `Edit`, `Write`, `MultiEdit` va `Bash` dan
keyin `~/.aiwork/journal.ndjson` ga bitta qator qo'shadi: qaysi asbob, qaysi
fayl, qachon. Tarmoqqa chiqmaydi, hech qanday HTTP so'rov qilmaydi va har qanday
xatoda jim `exit 0` qaytaradi.

**Sir yozilmaydi.** `Bash` uchun buyruqning faqat **birinchi so'zi** saqlanadi
(`pytest`, `alembic`, `docker`). To'liq buyruq yozilsa, `export TOKEN=...` yoki
`psql "postgresql://user:parol@..."` avval diskka, keyin bazaga tushardi — va
u yerdan chiqarib bo'lmaydi, jurnal faqat qo'shiladi. Diff va fayl mazmuni
umuman saqlanmaydi.

**Izni serverga agent olib ketadi.** Alohida demon (systemd/launchd/Windows
service) YO'Q va hozircha rejada emas: uch OS uchun uch xil xizmat eng ko'p
buziladigan qism bo'lardi. O'rniga to'rtta tool'da ixtiyoriy `pulses` parametri
bor — `start_session`, `report_progress`, `finish_task`, `report_unplanned`.
Agent serverga borganda jurnalning yuborilmagan qatorlarini o'zi uzatadi va
`~/.aiwork/offset` ni siljitadi. Qoidalar `SKILL.md` da.

**Agent umuman kelmasa** — jurnal diskda qoladi va qo'lda yuboriladi:

```powershell
.\push-pulses.ps1                 # Windows
.\push-pulses.ps1 -Read           # yubormaydi, JSON chiqaradi (agent uchun)
```
```bash
bash push-pulses.sh               # macOS / Linux
bash push-pulses.sh --all         # offset'ni inkor qilib, boshidan
```

Takroriy yuborish xavfsiz: server dublikatni `(client_sid, ts, tool, target)`
bo'yicha tashlaydi va `{"accepted":0,"dropped":N}` qaytaradi.

**Doskada nima ko'rinadi.** Vazifa jurnalida seans sarlavhasi ostida
«N fayl · M hisobot», va agar ish bo'lib hisobot yo'q bo'lsa — ogohlantirish.
`/agents` sahifasida yuqorida o'lchov qatori (necha seansda hisobot bor) va
«Sessiyasiz ish» bloki: kun va loyiha bo'yicha guruhlangan tahrirlar, har biriga
«Hisobot yozish» tugmasi. Odam yozgan hisobot jurnalda «odam yozdi» belgisi
bilan turadi — agentning ishi sifatida ko'rsatilmaydi.

Pulse'lar lentada **yozuv sifatida ko'rsatilmaydi**: bir kechada ularning
o'nlab bo'ladi, va odam hisobot o'qiydi, `Edit app/foo.py` ni emas.

---

## 8. Agent nima qila olmaydi

Bular cheklov emas, tuzilishning o'zi — «unut» deb aytishning hojati yo'q:

- **Vazifani yopa olmaydi.** Buning asbobi yo'q va bo'lmaydi ham. `completed` —
  «men o'z qismimni tugatdim», «bajarildi» emas.
- **Kartochkani ustundan ustunga ko'chira olmaydi.** Butun umri davomida bitta
  ko'chirish qiladi: ishga olganda, doskaning oqimi bo'yicha.
- **Ro'yxat punktini o'zgartira va o'chira olmaydi.** Faqat qo'sha oladi va
  bajarilganini belgilay oladi.
- **Belgilashda `note` majburiy.** Nima qilinganini aytmasdan punktni yopib
  bo'lmaydi. Belgilangan punktni qayta belgilash yangi ish sifatida hisoblanmaydi.
- **Ochiq ro'yxat ustidan «hammasi tayyor» deya olmaydi.** Belgilanmagan punkt
  qolgan bo'lsa, natija `partial` deb yoziladi va qolganlari ro'yxatga tushadi.

---

## 9. Muammolar

| Belgi | Sababi va yechimi |
|---|---|
| `401` yoki «token yaroqsiz» | `AIWORK_TOKEN` yo'q, xato yoki bekor qilingan. Terminalni qayta oching (`setx` eskisiga ta'sir qilmaydi), keyin yangi token so'rang. **Qayta-qayta urinmang.** |
| `Проект не найден` / «Loyiha topilmadi» | `.mcp.json` dagi `X-Aiwork-Project` slug'i xato yoki loyiha boshqa jamoada. Doskadagi slug bilan solishtiring yoki sarlavhani olib tashlang. |
| `/mcp` da `aiwork` yo'q | Claude Code loyiha papkasidan ishga tushirilmagan, yoki `.mcp.json` boshqa joyda. |
| `next_assignment` bo'sh qaytaradi | Doskada sizga biriktirilgan, `Navbatda`/`Bajarilmoqda` rolidagi vazifa yo'q. Kartochkada o'zingizni ijrochi qilib qo'ying. |
| Agent ro'yxatni ko'rmayapti | Kartochkada ro'yxat yo'q. Odam qo'shsin yoki agentga `add_checklist_items` bilan reja tuzishni ayting. |
| Talon ishlamadi | Kodlar bir martalik va muddati chegaralangan. Doskadan yangisini oling. |

---

## 10. Boshqa agentlar (Codex va h.k.)

Protokol standart, shuning uchun MCP'ni qo'llaydigan har qanday mijoz ulanadi.
Kerakli uchta narsa:

| Nima | Qiymati |
|---|---|
| Transport | Streamable HTTP (SSE emas, stdio emas) |
| Manzil | `https://work.ai-energy.team/mcp` |
| Sarlavhalar | `Authorization: Bearer <token>` va ixtiyoriy `X-Aiwork-Project: <slug>` |

Mahalliy ishga tushirilgan stek uchun manzil `http://127.0.0.1:8310/mcp`.
Mijozingiz HTTP-transportni qo'llamasa, `check.sh` ni namuna sifatida oling:
u xuddi shu chaqiruvlarni curl bilan qiladi.

Qoidalar fayli (`skills/aiwork/SKILL.md`) Claude Code uchun yozilgan, lekin u
oddiy markdown — boshqa agentga ham shuni ko'rsating (Codex uchun `AGENTS.md` ga
qo'shing).

**Faoliyat izi Codex uchun ishlamaydi — bu ochiq cheklov.** Hook mexanizmi
Claude Code'ga xos: `~/.claude/settings.json` dagi `PostToolUse` ni faqat u
o'qiydi. Codex va boshqa mijozlarda jurnal umuman to'lmaydi, shuning uchun
`push-pulses` yuboradigan narsa ham bo'lmaydi. Bu yerda ish faqat hisobotlar
orqali ko'rinadi — ya'ni ko'rsatma qanchalik bajarilganiga to'liq bog'liq.

---

## 11. Ichida nima bor

```
aiwork-client/
├── README.md               ← shu hujjat
├── ISHLATISH.md            ← qisqa yo'riqnoma: qadamlar, doskada nima ko'rinadi, muammolar
├── .mcp.json               ← MCP ulanishi (token muhitdan olinadi)
├── CLAUDE.md.snippet       ← loyihaning CLAUDE.md siga qo'shiladigan qism
├── skills/aiwork/SKILL.md  ← agent qoidalari: asboblar, ustunlar, ro'yxat, reportlar
├── install.ps1             ← Windows uchun o'rnatgich
├── install.sh              ← macOS/Linux uchun o'rnatgich
├── check.ps1               ← ulanish tekshiruvi (Windows), hech narsani o'zgartirmaydi
├── check.sh                ← ulanish tekshiruvi (macOS/Linux)
├── hooks/
│   ├── aiwork-pulse        ← faoliyat izi hook'i: tarmoqsiz, jimgina, exit 0
│   └── install-hook.py     ← hook'ni ~/.claude/settings.json ga qo'shadi
├── push-pulses.ps1         ← izni qo'lda yuborish (Windows)
└── push-pulses.sh          ← izni qo'lda yuborish (macOS/Linux)
```

`skills/aiwork/SKILL.md` va bu arxivning o'zi **qo'lda tahrirlanmaydi**: qoidalar
repodagi `.claude/skills/aiwork/SKILL.md` da yashaydi, to'plam esa
`python work-app/sync-client.py` bilan yig'iladi. Mos-nomosligini
`python work-app/sync-client.py --check` aytadi.
