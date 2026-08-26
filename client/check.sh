#!/usr/bin/env bash
# aiwork ulanishini tekshirish. Hech narsani o'zgartirmaydi: faqat o'qiydi.
#
#   bash check.sh
#   AIWORK_URL=http://127.0.0.1:8310/mcp bash check.sh     # mahalliy stek
#
# Token muhitdan olinadi (AIWORK_TOKEN), loyiha slug'i — .mcp.json dan yoki
# AIWORK_PROJECT dan.
set -euo pipefail

URL="${AIWORK_URL:-https://work.ai-energy.team/mcp}"
TOKEN="${AIWORK_TOKEN:-}"
PROJECT="${AIWORK_PROJECT:-}"

if [ -z "$TOKEN" ]; then
  echo "AIWORK_TOKEN muhitda yo'q. export AIWORK_TOKEN=\"...\" qiling." >&2
  exit 1
fi

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "python kerak (javoblarni o'qish uchun)" >&2; exit 1; }

# Loyiha slug'i .mcp.json da bo'lsa — o'shani olamiz: klient ham shundan ishlaydi.
if [ -z "$PROJECT" ] && [ -f .mcp.json ]; then
  PROJECT="$("$PY" -c "import json,sys
try:
    d = json.load(open('.mcp.json', encoding='utf-8'))
    print(d['mcpServers']['aiwork']['headers'].get('X-Aiwork-Project', ''))
except Exception:
    print('')" 2>/dev/null || true)"
fi

AUTH=(-H "Authorization: Bearer $TOKEN")
[ -n "$PROJECT" ] && AUTH+=(-H "X-Aiwork-Project: $PROJECT")
COMMON=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream")

say() { printf '\n\033[1m-- %s\033[0m\n' "$1"; }

echo "manzil:  $URL"
echo "loyiha:  ${PROJECT:-<hammasi>}"

# ── 1. Rukopojatie: seansni server sarlavhada beradi ─────────────────────────
say "ulanish"
HEADERS="$(mktemp)"
BODY="$(curl -sS -D "$HEADERS" "${COMMON[@]}" "${AUTH[@]}" -X POST "$URL" -d '{
  "jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-06-18","capabilities":{},
            "clientInfo":{"name":"check","version":"1"}}}')"

CODE="$(head -n1 "$HEADERS" | tr -d '\r' | awk '{print $2}')"
if [ "$CODE" = "401" ]; then
  echo "  401: token yaroqsiz yoki bekor qilingan. Yangisini so'rang." >&2
  rm -f "$HEADERS"; exit 1
fi
case "$BODY" in
  *'"error"'*) echo "  server rad etdi: $BODY" >&2; rm -f "$HEADERS"; exit 1;;
esac

SESSION="$(grep -i '^mcp-session-id:' "$HEADERS" | tr -d '\r' | cut -d' ' -f2)"
rm -f "$HEADERS"
echo "  ulandi, sessiya: ${SESSION:--}"
MCP=(-H "Mcp-Session-Id: $SESSION")

curl -sS -o /dev/null "${COMMON[@]}" "${AUTH[@]}" "${MCP[@]}" -X POST "$URL" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

call() { # call <id> <tool> <json-args>
  curl -sS "${COMMON[@]}" "${AUTH[@]}" "${MCP[@]}" -X POST "$URL" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":$1,\"method\":\"tools/call\",\"params\":{\"name\":\"$2\",\"arguments\":$3}}"
}

# ── 2. Asboblar ──────────────────────────────────────────────────────────────
say "asboblar"
curl -sS "${COMMON[@]}" "${AUTH[@]}" "${MCP[@]}" -X POST "$URL" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' |
  "$PY" -c 'import sys,json
d = json.load(sys.stdin)["result"]["tools"]
print("  soni:", len(d))
print(" ", ", ".join(t["name"] for t in d))'

# ── 3. Doska ustunlari va oqim ───────────────────────────────────────────────
say "ustunlar"
call 3 list_columns '{}' | "$PY" -c 'import sys,json
d = json.loads(json.load(sys.stdin)["result"]["content"][0]["text"])
by_id = {c["id"]: c["name"] for c in d["columns"]}
for c in d["columns"]:
    nxt = by_id.get(c["next_column_id"], "-")
    print("  %-20s %-10s -> %s" % (c["name"], c["kind"], nxt))'

# ── 4. Sizga tegishli ish ────────────────────────────────────────────────────
say "sizning vazifalaringiz"
call 4 list_my_tasks '{}' | "$PY" -c 'import sys,json
d = json.loads(json.load(sys.stdin)["result"]["content"][0]["text"])
tasks = d.get("tasks", [])
if not tasks:
    print("  sizga biriktirilgan vazifa topilmadi (doskada ijrochi sifatida belgilaning)")
for t in tasks[:10]:
    c = t.get("checklist") or {}
    mark = " [%s/%s]" % (c.get("done"), c.get("total")) if c.get("total") else ""
    print("  %-40s %-14s%s" % (t["title"][:40], t["column"], mark))
if d.get("warning"):
    print("  ogohlantirish:", d["warning"])'

# ── 5. Faoliyat izi ──────────────────────────────────────────────────────────
# Hook mustaqil qatlam: server bilan gaplashmaydi va MCP haqida bilmaydi.
# Shuning uchun tekshiruvi ham mahalliy — fayl, sozlama, jurnal.
say "faoliyat izi"
HOOK_INSTALLER=""
for candidate in "$(dirname "$0")/hooks/install-hook.py" "hooks/install-hook.py"; do
  [ -f "$candidate" ] && HOOK_INSTALLER="$candidate" && break
done
if [ -n "$HOOK_INSTALLER" ]; then
  "$PY" "$HOOK_INSTALLER" . --check || true
else
  echo "  hooks/install-hook.py topilmadi — to'plamdan tashqarida ishga tushirilgan"
fi

say "tayyor"
