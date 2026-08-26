#!/usr/bin/env bash
# aiwork klientini loyihaga o'rnatish (macOS / Linux).
#
#   bash install.sh ~/projects/mening-loyiham
#   AIWORK_NO_HOOK=1 bash install.sh ~/projects/x     # faoliyat izisiz
#
# Ko'chirishlardan iborat va boshqa hech narsa qilmaydi. Mavjud .mcp.json va
# CLAUDE.md ustiga yozilmaydi: ular loyihaniki, biznikimas.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  echo "Foydalanish: bash install.sh <loyiha-papkasi>" >&2
  exit 1
fi
if [ ! -d "$TARGET" ]; then
  echo "Papka topilmadi: $TARGET" >&2
  exit 1
fi

say() { printf '  %s\n' "$1"; }

# ── 1. MCP ulanishi ──────────────────────────────────────────────────────────
if [ -f "$TARGET/.mcp.json" ]; then
  if diff -q "$HERE/.mcp.json" "$TARGET/.mcp.json" >/dev/null 2>&1; then
    say ".mcp.json — allaqachon o'rnida"
  else
    say ".mcp.json BOR va boshqacha — tegilmadi. Farqi:"
    diff "$TARGET/.mcp.json" "$HERE/.mcp.json" || true
  fi
else
  cp "$HERE/.mcp.json" "$TARGET/.mcp.json"
  say ".mcp.json ko'chirildi"
fi

# ── 2. Qoidalar ──────────────────────────────────────────────────────────────
# Skill ustiga yoziladi ataylab: u qoidalarning yagona manbasi, va eskirgan
# nusxa bilan ishlagan agent xatosini bir oydan keyin payqashadi.
mkdir -p "$TARGET/.claude/skills/aiwork"
cp "$HERE/skills/aiwork/SKILL.md" "$TARGET/.claude/skills/aiwork/SKILL.md"
say ".claude/skills/aiwork/SKILL.md yangilandi"

# ── 3. CLAUDE.md ─────────────────────────────────────────────────────────────
if [ -f "$TARGET/CLAUDE.md" ] && grep -q "aiwork board over MCP" "$TARGET/CLAUDE.md"; then
  say "CLAUDE.md — aiwork bo'limi allaqachon bor"
else
  printf '\n' >> "$TARGET/CLAUDE.md"
  cat "$HERE/CLAUDE.md.snippet" >> "$TARGET/CLAUDE.md"
  say "CLAUDE.md ga aiwork bo'limi qo'shildi"
fi

# ── 4. Faoliyat izi (hook) ───────────────────────────────────────────────────
# Ko'rsatma ehtimollikni oshiradi, kafolat bermaydi. Hook deterministik: uni
# Claude Code runtime majburan chaqiradi, model qarori qatnashmaydi. Shuning
# uchun u ko'rsatmaning o'rnini emas, YONINI egallaydi: hisobot yozmaydi, faqat
# «ish bo'ldi» faktini qayd qiladi.
if [ -n "${AIWORK_NO_HOOK:-}" ]; then
  say "faoliyat izi: AIWORK_NO_HOOK qo'yilgan, o'tkazib yuborildi"
elif PY="$(command -v python3 || command -v python || true)"; [ -n "$PY" ]; then
  "$PY" "$HERE/hooks/install-hook.py" "$TARGET"
else
  say "faoliyat izi: python topilmadi, hook o'rnatilmadi"
fi

# ── 5. Kalit ─────────────────────────────────────────────────────────────────
if [ -z "${AIWORK_TOKEN:-}" ]; then
  echo
  echo "  DIQQAT: AIWORK_TOKEN muhitda yo'q." >&2
  echo "  ~/.zshrc yoki ~/.bashrc ga qo'shing:  export AIWORK_TOKEN=\"...\"" >&2
  echo "  Usiz har chaqiruv 401 qaytaradi." >&2
fi

echo
say "Tayyor. Endi tekshiring:  bash check.sh"
