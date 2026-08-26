# Faoliyat izini ishlatish — qadamlar

Bu qisqa yo'riqnoma. To'liq tavsif va sabablar `README.md` da (7-bo'lim,
«Faoliyat izi»). Bu yerda faqat nima qilish kerakligi.

**Nima uchun bu bor.** Ko'rsatma agentga «hisobot yoz» deydi, lekin uni model
o'qiydi va o'zi qaror qiladi — shuning uchun hisobot yozilmasligi mumkin, va
u holda doskada ishdan **umuman iz qolmaydi**. Hook boshqacha: uni Claude Code
runtime majburan chaqiradi. U hisobot yozmaydi — «ish bo'ldi» faktini qayd
qiladi, va doska ikkisi ajralib ketganini ko'rsatadi.

---

## 0. Avval `.mcp.json` ni tekshiring

Loyiha ildizidagi `.mcp.json` da **shu** turishi kerak:

```json
"Authorization": "Bearer ${AIWORK_TOKEN}"
```

Agar u yerda `"Bearer "` (bo'sh) yoki tirik tokenning o'zi yozilgan bo'lsa —
tuzatilishi kerak. Bo'sh bo'lsa har chaqiruv 401 qaytaradi va `aiwork`
asboblari umuman ishlamaydi; tirik token bo'lsa u repoga tushib ketishi mumkin.

Repodagi to'g'ri nusxadan tiklash:

```bash
git checkout HEAD -- .mcp.json
```

`HEAD --` qismi muhim: buzuq nusxa **indeksga** qo'yilgan bo'lsa, oddiy
`git checkout -- .mcp.json` uni indeksdan qaytaradi, ya'ni hech narsa
o'zgarmaydi va `git diff` jim turadi.

Token muhitda yashaydi, faylda emas:

```powershell
setx AIWORK_TOKEN "..."        # Windows — YANGI oynalarga ta'sir qiladi
```
```bash
export AIWORK_TOKEN="..."      # ~/.zshrc yoki ~/.bashrc ga
```

Tekshirish: `echo $env:AIWORK_TOKEN` / `echo $AIWORK_TOKEN`.

---

## 1. Hook'ni o'rnatish — bir marta, har loyiha uchun

```bash
python work-app/client/hooks/install-hook.py <loyiha-papkasi>
```

Shu repo uchun:

```bash
python work-app/client/hooks/install-hook.py C:\projects\ai-energy
```

Uch ish qiladi:

| Nima | Qayerga |
|---|---|
| `aiwork-pulse` ko'chiriladi | `~/.aiwork/aiwork-pulse` |
| loyiha yo'li yoziladi | `~/.aiwork/projects` |
| `PostToolUse` yozuvi **qo'shiladi** | `~/.claude/settings.json` |

`settings.json` ustiga yozilmaydi: unda model, tema, boshqa hook'lar bo'lsa
saqlanadi. Allaqachon `aiwork-pulse` bor bo'lsa takrorlanmaydi.

**Keyin Claude Code'ni qayta ishga tushiring** — sozlama faqat ochilishda
o'qiladi.

Holatini ko'rish:

```bash
python work-app/client/hooks/install-hook.py C:\projects\ai-energy --check
```

Kutilgan chiqish:

```
  hook fayli:      bor  (C:\Users\...\.aiwork\aiwork-pulse)
  settings.json:   ro'yxatda  (C:\Users\...\.claude\settings.json)
  kuzatiladi:      1 loyiha
  shu loyiha:      ha
  jurnal:          N qator
```

Hook kerak bo'lmasa: `install.ps1 -NoHook` / `AIWORK_NO_HOOK=1 bash install.sh`.

---

## 2. Undan keyin sizdan hech narsa talab qilinmaydi

Har `Edit`, `Write`, `MultiEdit`, `Bash` dan keyin `~/.aiwork/journal.ndjson`
ga bitta qator qo'shiladi:

```json
{"ts": 1787117593.31, "client_sid": "...", "tool": "Edit", "target": "app/mcp/tools.py", "cwd": "C:/projects/ai-energy"}
```

- **Tarmoqqa chiqmaydi.** Bitta HTTP so'rov ham qilmaydi.
- **Sekinlashtirmaydi.** Skriptning o'z ishi ~0.2 ms.
- **Hech qachon to'xtatmaydi.** Har qanday xatoda jim `exit 0`.
- **Sir yozilmaydi.** `Bash` uchun buyruqning faqat birinchi so'zi
  (`pytest`, `alembic`). Diff va fayl mazmuni umuman saqlanmaydi.

Izni serverga **agentning o'zi** olib ketadi: `start_session`,
`report_progress`, `finish_task`, `report_unplanned` da `pulses` parametri bor.
Qoidalar `.claude/skills/aiwork/SKILL.md` da.

---

## 3. Doskada nima ko'rinadi

`http://work.localhost:8304/agents` (yoki `https://work.ai-energy.team/agents`):

```
7 kun: 12 seans · 9 tasida hisobot bor (75%) · 3 tasi sessiyasiz
```

Ulush **80% dan past** bo'lsa boshqa rangda — bu keyingi qaror uchun signal
(demon kerakmi yoki ko'rsatma yetdimi).

```
┌ Sessiyasiz ish (3 kun)
│  19-avgust · speaking · 7 fayl · 02:20–02:32     [Hisobot yozish]
│  18-avgust · speaking · 12 fayl · 14:00–14:33    [Hisobot yozish]
└
```

Bu blok **bo'sh bo'lsa umuman ko'rinmaydi**. `[Hisobot yozish]` vazifani
**qo'lda** tanlashni talab qiladi: pulse — fakt, niyat emas, va «bu fayl o'sha
vazifaga tegishli edi» degan bog'lanishni faqat odam biladi. Yozilgan hisobot
jurnalda «odam yozdi» belgisi bilan turadi.

Vazifa oynasida, seans sarlavhasi ostida:

```
Seans · claude_code · main · 09:20–11:45 · ketmoqda
47 fayl · 12 hisobot

Seans · claude_code · main · 14:00–16:30 · uzilib qolgan
38 fayl · 0 hisobot     ⚠ Ish bo'lgan, hisobot yo'q
```

Pulse'lar lentada yozuv sifatida **ko'rsatilmaydi** — bir kechada ularning
o'nlab bo'ladi, va odam hisobot o'qiydi, `Edit app/foo.py` ni emas. Sarlavhadagi
songa bosilsa tegilgan fayllar ro'yxati ochiladi.

---

## 4. Agent serverga umuman kelmasa — qo'lda yuborish

```powershell
.\push-pulses.ps1                # yuborilmagan qatorlarni yuboradi
.\push-pulses.ps1 -Read          # yubormaydi, JSON chiqaradi (agent uchun)
.\push-pulses.ps1 -All           # offset'ni inkor qilib, boshidan
```
```bash
bash push-pulses.sh
bash push-pulses.sh --read
bash push-pulses.sh --all
```

Mahalliy stek uchun: `AIWORK_API=http://127.0.0.1:8300`.

**Takroriy yuborish xavfsiz.** Server dublikatni `(client_sid, ts, tool, target)`
bo'yicha tashlaydi va `{"accepted":0,"dropped":N}` qaytaradi. Shuning uchun
«ikki marta yubordimmi?» degan savol ahamiyatsiz.

`offset` — **yuborilgan qatorlar soni** (`~/.aiwork/offset`), bayt emas. Faqat
muvaffaqiyatdan keyin siljiydi.

---

## 5. Yangi loyiha qo'shganda

To'liq to'plam bilan (`.mcp.json`, skill, `CLAUDE.md`, hook — hammasi birga):

```powershell
# work-app/aiwork-client.zip ni yechib, ichidan:
.\install.ps1 -Target C:\projects\boshqa-loyiha
.\check.ps1
```
```bash
bash install.sh ~/projects/boshqa-loyiha
bash check.sh
```

`.mcp.json` dagi `X-Aiwork-Project` ni o'sha repoga mos loyiha slug'iga
o'zgartiring.

---

## Bilib qo'yish kerak bo'lgan uch narsa

**Hook global ro'yxatga olinadi.** `~/.claude/settings.json` — bitta fayl butun
mashina uchun, ya'ni hook har qanday loyihada chaqiriladi. Shuning uchun
`~/.aiwork/projects` filtri bor: faqat o'sha papkalar ichidagi ish yoziladi.
Usiz begona repozitoriyning fayl yo'llari jamoaning bazasiga tushardi. **Yangi
loyiha qo'shsangiz `install-hook.py` ni o'sha loyiha uchun ham ishga
tushirish kerak** — aks holda uning ishi jimgina yozilmaydi.

**Codex va boshqa mijozlarda ishlamaydi.** `PostToolUse` mexanizmi Claude
Code'ga xos. U yerda jurnal to'lmaydi, `push-pulses` ham yuboradigan narsa
topmaydi — ish faqat hisobotlar orqali ko'rinadi, ya'ni ko'rsatma qanchalik
bajarilganiga to'liq bog'liq. Bu ochiq cheklov.

**Demon yo'q va bu ataylab.** systemd/launchd/Windows service — 2-bosqich.
Uch OS uchun uch xil xizmat eng ko'p buziladigan qism bo'lardi, va uning
qiymati hozircha isbotlanmagan. `/agents` tepasidagi foiz shuni hal qiladi:
80% dan past bo'lsa demon asoslanadi.

---

## Muammolar

| Belgi | Sababi |
|---|---|
| `/mcp` da `aiwork` yo'q yoki 401 | `.mcp.json` da `Bearer ` bo'sh, yoki `AIWORK_TOKEN` muhitda yo'q. `setx` **yangi** oynalarga ta'sir qiladi — terminalni qayta oching |
| `jurnal: hali bo'sh` | hook `settings.json` ga qo'shilgandan keyin Claude Code qayta ishga tushirilmagan |
| ish bo'ldi, jurnal to'lmayapti | loyiha `~/.aiwork/projects` da yo'q — `install-hook.py <loyiha>` ni shu loyiha uchun ishga tushiring |
| `push-pulses` 404 | `.mcp.json` dagi loyiha slug'i boshqa jamoada yoki arxivlangan |
| `/agents` da «Sessiyasiz ish» yo'q | bu normal: bog'lanmagan pulse bo'lmasa blok umuman ko'rinmaydi |
| doskada sinov ma'lumoti qolgan | `docker compose exec -T postgres psql -U aiwork -d aiwork < backend/docs/pulse-check-cleanup.sql` |

Hook'ning o'zini alohida sinash (tarmoq kerak emas):

```bash
echo '{"session_id":"test","tool_name":"Edit","tool_input":{"file_path":"a.py"},"cwd":"'"$PWD"'"}' \
  | python ~/.aiwork/aiwork-pulse
cat ~/.aiwork/journal.ndjson
```

Buzuq JSON bersangiz ham `exit 0` bo'lishi kerak.
