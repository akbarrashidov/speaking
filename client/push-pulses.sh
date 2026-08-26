#!/usr/bin/env bash
# Faoliyat izini serverga yuborish (macOS / Linux).
#
#   bash push-pulses.sh              # yuborilmagan qatorlarni yuboradi
#   bash push-pulses.sh --read       # hech narsa yubormaydi, JSON massiv chiqaradi
#   bash push-pulses.sh --all        # offset'ni inkor qilib, jurnalni boshidan
#
# Bu ZAXIRA yo'l. Odatda izni agentning o'zi olib ketadi: `start_session`,
# `report_progress`, `finish_task`, `report_unplanned` tool'larining `pulses`
# parametri bor. Bu skript agent serverga umuman kelmagan holat uchun — jurnal
# diskda qolib ketganda odam qo'lda ishga tushiradi.
#
# `--read` — agent uchun: chiqishini to'g'ridan-to'g'ri `pulses` parametriga
# beriladi, keyin offset siljitiladi (pastga qarang).
set -euo pipefail

JOURNAL="${AIWORK_JOURNAL:-$HOME/.aiwork/journal.ndjson}"
OFFSET="${AIWORK_OFFSET:-$HOME/.aiwork/offset}"
API="${AIWORK_API:-https://work.ai-energy.team}"
TOKEN="${AIWORK_TOKEN:-}"
PROJECT="${AIWORK_PROJECT:-}"
# Serverning bir chaqiruvdagi chegarasi. Qolgani diskda qoladi va keyingi
# chaqiruvda ketadi.
BATCH=200

MODE="push"
for arg in "$@"; do
  case "$arg" in
    --read) MODE="read";;
    --all) OFFSET="";;
    *) echo "Noma'lum argument: $arg" >&2; exit 1;;
  esac
done

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "python kerak" >&2; exit 1; }

if [ ! -f "$JOURNAL" ]; then
  echo "Jurnal yo'q: $JOURNAL — hook hali bir marta ham ishlamagan." >&2
  exit 0
fi

# Offset — YUBORILGAN QATORLAR SONI, bayt emas. Ataylab: qator sonini har
# qanday muhitda bir buyruq bilan o'qib bo'ladi, bayt bilan `seek` kerak
# bo'lardi. Aylanish (10 MB) yoki jurnalning qisqarishi offset'ni jurnaldan
# katta qilib qo'yishi mumkin — bunda noldan boshlanadi. Ortiqcha yuborilgan
# qatorlarni server dublikat sifatida tashlaydi, shuning uchun bu xavfsiz.
SENT=0
if [ -n "$OFFSET" ] && [ -f "$OFFSET" ]; then
  SENT="$(tr -dc '0-9' < "$OFFSET" || true)"
  SENT="${SENT:-0}"
fi
TOTAL="$(wc -l < "$JOURNAL" | tr -d ' ')"
[ "$SENT" -le "$TOTAL" ] || SENT=0

BODY="$(tail -n "+$((SENT + 1))" "$JOURNAL" | head -n "$BATCH" |
  "$PY" -c 'import json,sys
rows = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        row = json.loads(line)
    except ValueError:
        continue        # bitta buzuq qator butun pachkani bekor qilmaydi
    rows.append({k: row.get(k) for k in ("ts", "client_sid", "tool", "target")})
print(json.dumps({"pulses": rows}, ensure_ascii=False))')"

COUNT="$("$PY" -c 'import json,sys; print(len(json.loads(sys.stdin.read())["pulses"]))' <<<"$BODY")"

if [ "$MODE" = "read" ]; then
  "$PY" -c 'import json,sys; print(json.dumps(json.loads(sys.stdin.read())["pulses"], ensure_ascii=False, indent=2))' <<<"$BODY"
  echo "# $COUNT qator. Yuborgandan keyin: echo $((SENT + COUNT)) > $OFFSET" >&2
  exit 0
fi

if [ "$COUNT" = "0" ]; then
  echo "Yuboriladigan yangi qator yo'q ($TOTAL dan $SENT tasi ketgan)."
  exit 0
fi

if [ -z "$TOKEN" ]; then
  echo "AIWORK_TOKEN muhitda yo'q. export AIWORK_TOKEN=\"...\" qiling." >&2
  exit 1
fi

# Loyiha slug'i .mcp.json dan — klient ham shundan ishlaydi.
if [ -z "$PROJECT" ] && [ -f .mcp.json ]; then
  PROJECT="$("$PY" -c "import json
try:
    d = json.load(open('.mcp.json', encoding='utf-8'))
    print(d['mcpServers']['aiwork']['headers'].get('X-Aiwork-Project', ''))
except Exception:
    print('')" 2>/dev/null || true)"
fi
if [ -n "$PROJECT" ]; then
  BODY="$("$PY" -c "import json,sys
d = json.loads(sys.stdin.read()); d['project'] = '$PROJECT'; print(json.dumps(d, ensure_ascii=False))" <<<"$BODY")"
fi

echo "manzil:  $API/api/cli/pulses"
echo "loyiha:  ${PROJECT:-<hammasi>}"
echo "pachka:  $COUNT qator ($TOTAL dan $SENT tasi avval ketgan)"

RESPONSE="$(curl -sS -w '\n%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -X POST "$API/api/cli/pulses" --data-binary "$BODY")"
CODE="$(tail -n1 <<<"$RESPONSE")"
PAYLOAD="$(sed '$d' <<<"$RESPONSE")"

case "$CODE" in
  200)
    echo "  javob: $PAYLOAD"
    # Offset faqat muvaffaqiyatdan keyin siljiydi. Aks holda uzilgan
    # yuborishdan keyin ish jimgina yo'qolardi — bu esa aynan o'sha
    # muammoning o'zi.
    if [ -n "${AIWORK_OFFSET:-$HOME/.aiwork/offset}" ]; then
      mkdir -p "$(dirname "${AIWORK_OFFSET:-$HOME/.aiwork/offset}")"
      echo "$((SENT + COUNT))" > "${AIWORK_OFFSET:-$HOME/.aiwork/offset}"
    fi
    echo "  offset: $((SENT + COUNT))"
    ;;
  401) echo "  401: token yaroqsiz yoki bekor qilingan. Yangisini so'rang." >&2; exit 1;;
  404) echo "  404: loyiha topilmadi yoki sizga ko'rinmaydi ($PROJECT)." >&2; exit 1;;
  *)   echo "  $CODE: $PAYLOAD" >&2; exit 1;;
esac
