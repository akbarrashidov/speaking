# aiwork — nima qayerga va qanday buyruq

---

## Fayllar

| Fayl | Qayerga |
|---|---|
| `.mcp.json` | repo ildizi |
| `SKILL.md` | `<repo>/.claude/skills/aiwork/SKILL.md` |
| `CLAUDE.md` bo'limi | repo ildizi (Claude Code) |
| `AGENTS.md` bo'limi | repo ildizi (Codex) |
| `aiwork-pulse` | `~/.aiwork/aiwork-pulse` — o'rnatuvchi qo'yadi |
| hook yozuvi | `~/.claude/settings.json` — o'rnatuvchi qo'shadi |
| qisqa buyruqlar | `<repo>/.claude/commands/aiwork/` — yetti fayl |

`SKILL.md` aynan `.claude/skills/` da bo'lishi kerak — Claude Code faqat
shu yo'ldan skill'ni o'zi topadi.

---

## Token — ikki variant

### Variant 1: muhit o'zgaruvchisi (tavsiya etiladi)

`.mcp.json` da:

```json
"Authorization": "Bearer ${AIWORK_TOKEN}"
```

```powershell
setx AIWORK_TOKEN "..."           # keyin YANGI terminal
```
```bash
echo 'export AIWORK_TOKEN="..."' >> ~/.bashrc && source ~/.bashrc
```

`.mcp.json` git'da qoladi — ichida sir yo'q. Token almashsa bir joy
yangilanadi, hamma loyihada birdan ishlaydi.

### Variant 2: token to'g'ridan-to'g'ri faylda

```json
"Authorization": "Bearer ss1LWa0dRxzJQFKFTPHe5KuRLMGnFmFHhguwScDJuyY"
```

Unda `.mcp.json` **git'ga tushmasligi shart**:

```bash
echo ".mcp.json" >> .gitignore
git rm --cached .mcp.json          # allaqachon kuzatilgan bo'lsa
```

Va jamoa uchun shablon qoldirasiz — `.mcp.json.example`, token o'rniga
`${AIWORK_TOKEN}` bilan. Yangi odam uni nusxalab, o'z tokenini qo'yadi.

Bu variantda token har repoda takrorlanadi va almashganda hammasini
qo'lda yangilash kerak.

---

## Nusxalash — o'rnatish emas

Repo ichidagi fayllarni to'g'ri joyga qo'ysangiz yetadi. Hech narsa
o'rnatilmaydi, kompilyatsiya yo'q.

```
<repo>/
├── .mcp.json
├── CLAUDE.md                          ← bo'lim qo'shiladi
├── AGENTS.md                          ← bo'lim qo'shiladi
└── .claude/
    ├── skills/aiwork/SKILL.md
    └── commands/aiwork/*.md           ← yetti fayl
```

Claude Code ularni ishga tushganda o'zi o'qiydi.

`install.ps1` / `install.sh` shu nusxalashni qiladi — qulaylik uchun,
majburiy emas. Mavjud `.mcp.json` va `CLAUDE.md` ustiga yozmaydi, skill
esa ustiga yoziladi (u yagona manba bo'lishi kerak).

---

## Faqat hook o'rnatiladi

Hook — yagona qism, uni qo'lda qo'yish yetmaydi: u `~/.claude/settings.json`
ga yozuv qo'shishi kerak, va u fayl butun mashina uchun bitta.

```bash
python work-app/client/hooks/install-hook.py C:\projects\loyiha
```

Uch ish qiladi:

| Nima | Qayerga |
|---|---|
| `aiwork-pulse` ko'chiriladi | `~/.aiwork/aiwork-pulse` |
| loyiha yo'li yoziladi | `~/.aiwork/projects` |
| `PostToolUse` yozuvi qo'shiladi | `~/.claude/settings.json` |

Uchinchisi **qo'shiladi**, ustiga yozilmaydi — u fayldagi model, tema va
boshqa hook'lar saqlanadi.

**Keyin Claude Code'ni qayta ishga tushirish kerak** — sozlama faqat
ochilishda o'qiladi.

Holatni ko'rish:

```bash
python work-app/client/hooks/install-hook.py C:\projects\loyiha --check
```

Hook har yangi loyiha uchun qayta ishga tushirilishi kerak —
`~/.aiwork/projects` filtri shu ro'yxatdan tashqaridagi ishni yozmaydi
(begona repozitoriyning fayl yo'llari jamoa bazasiga tushmasin deb).

Hook kerak bo'lmasa — umuman o'rnatmasangiz ham hammasi ishlaydi, faqat
faoliyat izi bo'lmaydi.

---

## Tekshirish

```
claude
/mcp
```

`aiwork · connected` bo'lishi kerak. Keyin:

```
> aiwork'dan vazifalarimni ko'rsat
```

Vazifalar kelishi va javobda `warning` bo'lmasligi kerak.

Hook holati:

```bash
python work-app/client/hooks/install-hook.py <loyiha> --check
```

`jurnal: N qator` ko'rinishi kerak. `hali bo'sh` bo'lsa — Claude Code
hook qo'shilgandan keyin qayta ishga tushirilmagan.

### Izni qo'lda yuborish

Agent chaqirmagan bo'lsa:

```powershell
.\push-pulses.ps1
```
```bash
bash push-pulses.sh
```

Takroriy yuborish xavfsiz — server dublikatni tashlaydi.

---

## Qisqa buyruqlar

Fayllarni `<repo>/.claude/commands/aiwork/` ga qo'yasiz — yetti fayl,
har biri bitta buyruq. Hamma loyihada ishlashi kerak bo'lsa
`~/.claude/commands/aiwork/` ga qo'yasiz.

| Buyruq | Nima qiladi |
|---|---|
| `/aiwork:tasks` | ochiq vazifalarni ro'yxat qilib ko'rsatadi |
| `/aiwork:start 2` | vazifani oladi — seans + `claim_task` |
| `/aiwork:take AIW-7F3K` | talon kodi bilan oladi |
| `/aiwork:note testlar o'tdi` | oraliq hisobot; matn berilmasa o'zi yozadi |
| `/aiwork:done` | yakuniy hisobot, «Tasdiq kutilmoqda» |
| `/aiwork:unplanned CRLF bugi tuzatildi` | «Rejadan tashqari» ustuniga |
| `/aiwork:status` | ulanish, seans, yopilmagan vazifalar |

`/aiwork:note` va `/aiwork:done` jurnaldagi izni ham yuboradi.

Buyruqlar **agent o'zi chaqirishini almashtirmaydi** — ko'rsatma o'z
o'rnida qoladi. Bular agent unutgan yoki siz aniq nazorat qilmoqchi
bo'lgan holatlar uchun.

Tekshirish: `claude` ichida `/` bosilganda ro'yxatda `aiwork:` bilan
boshlanadigan yettitasi ko'rinishi kerak. Ko'rinmasa — fayllar noto'g'ri
joyda yoki frontmatter buzuq.

---

```
1. install.ps1 -Target <loyiha>
2. .mcp.json da X-Aiwork-Project ni slug'ga moslash
3. install-hook.py <loyiha>       → keyin Claude Code'ni qayta ishga tushirish
```

Uchinchi qadam o'tkazib yuborilsa — hook ishlamaydi va buni hech narsa
aytmaydi. Ish jimgina yozilmay qoladi.

---

## Yangi loyiha qo'shganda — uch qadam

```
1. Fayllarni nusxalash: .mcp.json, .claude/skills/, .claude/commands/,
   CLAUDE.md va AGENTS.md ga bo'lim
2. .mcp.json da X-Aiwork-Project ni loyiha slug'iga moslash
3. install-hook.py <loyiha>  → keyin Claude Code'ni qayta ishga tushirish
```

Uchinchi qadam o'tkazib yuborilsa — hook ishlamaydi va buni hech narsa
aytmaydi. Ish jimgina yozilmay qoladi.

---

## Muammolar

| Belgi | Sababi |
|---|---|
| `/mcp` da `aiwork` yo'q | `.mcp.json` repo ildizida emas yoki JSON buzuq |
| `failed`, 401 | token muhitda yo'q yoki bekor qilingan. `setx` faqat **yangi** terminallarga ta'sir qiladi |
| 404 | loyiha slug'i boshqa jamoada, arxivlangan, yoki token boshqa jamoaga bog'langan |
| `warning: project not resolved` | `X-Aiwork-Project` yetib bormagan |
| jurnal bo'sh | hook qo'shilgandan keyin Claude Code qayta ishga tushirilmagan, yoki loyiha `~/.aiwork/projects` da yo'q |
| `aiwork` ikki marta | `.mcp.json` va `~/.claude.json` da bir xil nom |

Oxirgi holatda `claude mcp remove aiwork` **ishlatilmasin** — u
`.mcp.json` ni buzadi. `~/.claude.json` dagi yozuv qo'lda olib tashlanadi.
