#!/usr/bin/env python
"""Faoliyat izi hook'ini ro'yxatga olish.

    python install-hook.py <loyiha-papkasi>
    python install-hook.py <loyiha-papkasi> --check    # tegmaydi, holatini aytadi

Uchta ish:

  1. `aiwork-pulse` ni `~/.aiwork/aiwork-pulse` ga ko'chiradi — hook global
     ro'yxatga olinadi, ya'ni yo'li mutlaq va barqaror bo'lishi kerak;
  2. loyiha ildizini `~/.aiwork/projects` ga yozadi — hook faqat shu
     papkalar ichidagi ishni qayd qiladi;
  3. `~/.claude/settings.json` ning `hooks.PostToolUse` massiviga bitta yozuv
     QO'SHADI.

Nega alohida skript va nega Python: `install.ps1` va `install.sh` ikkisi ham
shu yerga keladi. JSON'ni ehtiyotkorlik bilan birlashtirish — mavjud
`hooks` ni saqlab, o'zini takrorlamaslik — bash va PowerShell da ikki xil
yozilsa, ikkisi bir kuni ajralib ketadi va buni faqat kimningdir sozlamasi
yo'qolganda payqashadi.

**Ustidan yozilmaydi.** `settings.json` odamning fayli: unda model, tema,
boshqa hook'lar turadi. O'qiladi, bitta yozuv qo'shiladi, qaytariladi.
Allaqachon `aiwork-pulse` bor bo'lsa — hech narsa qilinmaydi.
"""
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MATCHER = "Edit|Write|MultiEdit|Bash"
# Yozuvni shu bilan tanib olamiz: yo'l mashinaga qarab boshqacha bo'ladi,
# fayl nomi esa o'zgarmaydi.
MARK = "aiwork-pulse"


def home() -> Path:
    return Path(os.path.expanduser("~"))


def settings_path() -> Path:
    return home() / ".claude" / "settings.json"


def hook_command(target: Path) -> str:
    """Hook chaqirig'i. Python bilan, chunki faylning kengaytmasi yo'q va
    Windows uni o'zi ishga tushira olmaydi."""
    runner = "python3" if os.name != "nt" else "python"
    return f'{runner} "{target}"'


def register(settings: dict, command: str) -> bool:
    """`hooks.PostToolUse` ga bitta yozuv qo'shish. Qo'shildimi — True."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("settings.json dagi `hooks` obyekt emas — qo'lda tuzatilishi kerak")
    events = hooks.setdefault("PostToolUse", [])
    if not isinstance(events, list):
        raise SystemExit("settings.json dagi `hooks.PostToolUse` massiv emas")

    for entry in events:
        for item in (entry or {}).get("hooks", []) or []:
            if MARK in str((item or {}).get("command") or ""):
                return False

    events.append(
        {"matcher": MATCHER, "hooks": [{"type": "command", "command": command}]}
    )
    return True


def add_root(folder: Path, project: Path) -> bool:
    """Loyiha ildizini kuzatilayotganlar ro'yxatiga qo'shish."""
    path = folder / "projects"
    existing = []
    if path.exists():
        existing = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    wanted = str(project)
    if wanted in existing:
        return False
    existing = [line for line in existing if line] + [wanted]
    path.write_text("\n".join(existing) + "\n", encoding="utf-8")
    return True


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    if not args:
        raise SystemExit("Foydalanish: python install-hook.py <loyiha-papkasi> [--check]")
    project = Path(args[0]).resolve()
    if not project.is_dir():
        raise SystemExit(f"Papka topilmadi: {project}")

    folder = home() / ".aiwork"
    target = folder / MARK
    config = settings_path()
    settings = {}
    if config.exists():
        try:
            settings = json.loads(config.read_text(encoding="utf-8") or "{}")
        except ValueError:
            raise SystemExit(f"{config} buzuq JSON — tegmadim, qo'lda tuzating")

    if check:
        registered = any(
            MARK in str((item or {}).get("command") or "")
            for entry in (settings.get("hooks", {}) or {}).get("PostToolUse", []) or []
            for item in (entry or {}).get("hooks", []) or []
        )
        roots = []
        if (folder / "projects").exists():
            roots = [
                line.strip()
                for line in (folder / "projects").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        missing = "YO'Q"
        print("  hook fayli:      %s  (%s)" % ("bor" if target.exists() else missing, target))
        print(
            "  settings.json:   %s  (%s)"
            % ("ro'yxatda" if registered else "RO'YXATDA EMAS", config)
        )
        print("  kuzatiladi:      %d loyiha" % len(roots))
        print("  shu loyiha:      %s" % ("ha" if str(project) in roots else missing))
        journal = folder / "journal.ndjson"
        if journal.exists():
            lines = sum(1 for _ in journal.open(encoding="utf-8"))
            print(f"  jurnal:          {lines} qator ({journal})")
        else:
            print("  jurnal:          hali bo'sh - hook bir marta ham ishlamagan")
        raise SystemExit(0 if registered and target.exists() else 1)

    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / MARK, target)
    # POSIX'da bajarilish huquqi kerak emas (chaqiruv `python <fayl>`), lekin
    # qo'lda sinab ko'rish uchun qulay.
    if os.name != "nt":
        os.chmod(target, 0o755)
    print(f"  {target} ko'chirildi")

    if add_root(folder, project):
        print(f"  {folder / 'projects'} ga qo'shildi: {project}")
    else:
        print("  loyiha allaqachon kuzatiladi")

    if register(settings, hook_command(target)):
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  {config} ga PostToolUse yozuvi qo'shildi")
        print("  Claude Code'ni qayta ishga tushiring - sozlama ochilishda o'qiladi.")
    else:
        print("  settings.json - aiwork-pulse allaqachon ro'yxatda")


if __name__ == "__main__":
    main()
