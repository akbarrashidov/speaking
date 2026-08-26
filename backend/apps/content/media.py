"""Shadowing videosi qayerdan kelishini aniqlaydi.

Ikki yo'l bor va ikkalasi ham qonuniy:

  * **YouTube havolasi** — video YUKLAB OLINMAYDI. Havola saqlanadi, o'quvchi
    brauzerida esa YouTube pleyerining o'zi ochiladi va faqat kerakli oraliq
    o'ynatiladi. Ko'rish YouTube tomonida hisoblanadi, mualliflik huquqi
    egasining nazorati saqlanadi.
  * **Yuklangan fayl** — o'zingiz suratga olgan yoki litsenziyasi ruxsat
    beradigan video (admin orqali, `/media/` ga tushadi).

Videoni YouTube'dan yuklab olib, ilova ichida tarqatish bu ro'yxatda yo'q:
u YouTube shartlariga ham, mualliflik huquqiga ham ziddir.
"""

from __future__ import annotations

import re

# youtube.com/watch?v=ID, youtu.be/ID, /embed/ID, /shorts/ID
YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^&]*&)*v=|embed/|shorts/|live/)|youtu\.be/)([\w-]{11})"
)

YOUTUBE = "youtube"
FILE = "file"


def youtube_id(url: str) -> str:
    """Havoladagi video identifikatori. YouTube bo'lmasa — bo'sh satr."""
    found = YOUTUBE_RE.search(url or "")
    return found.group(1) if found else ""


def media_kind(url: str) -> str:
    """`youtube`, `file` yoki bo'sh satr (video umuman yo'q)."""
    if not url:
        return ""
    return YOUTUBE if youtube_id(url) else FILE


def media_ref(url: str) -> str:
    """Klient nima bilan ishlashi: YouTube uchun ID, aks holda manzilning o'zi."""
    return youtube_id(url) or (url or "")
