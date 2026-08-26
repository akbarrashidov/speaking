"""System prompt yig'ilishi (§5.2).

Shablonlar `prompts/` papkasidagi versiyalangan fayllarda, DB'da emas.
Savollar ro'yxati promptga KIRITILMAYDI — model oldinga sakramasligi uchun
savollar tool response orqali bittalab beriladi.
"""

from __future__ import annotations

import functools
import hashlib
import logging

from django.conf import settings

from apps.content.models import FREE_FLOW_MODES, SessionMode

from . import adaptive, translate

logger = logging.getLogger(__name__)

# v2.0.0 — model endi baholamaydi va savol tanlamaydi (tool olib tashlandi).
# Butun qaror `coach.py` + `state.py` da; Live faqat gapiradi va eshitadi.
# v2.1.0 — DIRECTOR kontrakti kuchaytirildi (model ko'rsatmani ovoz chiqarib
# o'qib yuborgan edi) va erkin suhbat endi savol ro'yxati tugagach ham
# to'xtamaydi, har navbatni o'quvchining oxirgi javobidan quradi.
# v3.0.0 — darajalar (A0..B2) olib tashlandi. Endi mavzu grammatikani beradi,
# darajani esa o'quvchining o'z nutqi belgilaydi: `levels/*.md` o'rniga
# ko'zgu bloki (`adaptive.register_block`).
# v3.1.0 — ikkinchi yo'nalish: IBORALAR. Mavzuda `focus_phrase` bo'lsa,
# maqsad shakl emas, aynan o'sha ibora (`_phrase_focus_block`).
# v3.2.0 — shadowing videodan boradi (`_video_shadowing_block`: gapni video
# aytadi, AI faqat qisqa xulosani), rol suhbat esa sahna oladi
# (`_scene_block`: AI kim va qayerda).
# v4.0.0 — erkin suhbatda tuzatishni model O'ZI topadi (`self_correction.md`).
# Ilgari u DIRECTOR ni kutardi, DIRECTOR esa coach chaqiruvidan keyin kelardi:
# har navbat ~2 s jimlik. Endi baholash fonda ishlaydi va faqat ekranga
# chiqadi, ovoz esa kutmaydi (§consumer._close_turn_live_first).
# v4.1.0 — xato o'quvchining O'Z TILIDA tushuntiriladi va gap qayta aytiriladi
# (`_explanation_language_block`). Inglizcha tuzatishni A1 o'quvchi tuzatish deb
# ham anglamasdi; eshitish esa aytishning o'rnini bosmaydi.
# v4.2.0 — daraja aniqlash rejimi (`modes/placement.md` + zinapoya bloki):
# mavzu ham, maqsad struktura ham, tuzatish ham yo'q — faqat o'lchov.
PROMPT_VERSION = "v4.2.0"


@functools.lru_cache(maxsize=64)
def _read(relative: str) -> str:
    path = settings.PROMPTS_DIR / relative
    if not path.exists():
        logger.warning("Prompt fayli topilmadi: %s", path)
        return ""
    return path.read_text(encoding="utf-8").strip()


def _session_goals_block(questions: list[str], target_structure: str) -> str:
    """Erkin suhbat uchun savollar — skript emas, boshlanish nuqtasi.

    Drill/guided rejimlarida savollar bittalab DIRECTOR orqali beriladi, chunki
    u yerda ular o'lchanadigan element. Adaptive rejimda esa aksincha: model
    savolni o'quvchining aytganiga moslab qayta yozishi kerak, shuning uchun
    butun ro'yxatni oldindan ko'radi.

    Ro'yxat qisqa bo'lishi mumkin (bankda 2-3 savol) — shuning uchun bu yerda
    ochiq aytiladi: ro'yxat tugashi suhbat tugashi EMAS. Aks holda model
    "xayr" deb sessiyani o'zi yopib qo'yadi.
    """
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    return (
        "SESSION GOALS — starting points, not a script and not a limit. Cover "
        "them naturally, adapting each one to what the learner has already "
        f"told you:\n{numbered}\n"
        f"Target structure: {target_structure}.\n"
        "A goal is covered the moment the learner tells you the answer, whether "
        "or not you asked for it. One full answer can cover three goals at once "
        "— cross off every one of them and never come back to it. Asking again "
        "for something they have already told you is the one thing that makes "
        "this stop feeling like a conversation.\n"
        "This list is short on purpose. When you have covered it, keep the "
        "conversation going on the same theme with your own questions — the "
        "list running out is never a reason to end or wind down the session."
    )


def _phrase_focus_block(phrase: str) -> str:
    """Ibora yo'nalishi uchun fokus — bu yerda maqsad shakl emas, AYNAN ibora.

    Grammatikada o'quvchi shaklni ishlatsa yetarli; iborada esa aynan o'sha
    so'zlar chiqishi kerak, aks holda mashq bo'lmaydi. Shuning uchun bu blok
    grammatik fokusning ustiga qo'shiladi va undan kuchliroq turadi.
    """
    return (
        "PHRASE FOCUS — this session is about ONE fixed expression:\n"
        f'- The expression is: "{phrase}".\n'
        "- Every question you ask must make the natural answer contain that "
        "expression. If the learner answers without it, accept the meaning, "
        "then say the same idea back using the expression, and ask one more "
        "question that needs it again.\n"
        "- Use the expression yourself in your own turns, in different "
        "situations, so the learner hears where it fits.\n"
        "- Never spell it out as a rule and never say the words "
        '"expression" or "phrase" — just keep the conversation in a place '
        "where it is the natural thing to say."
    )


def _scene_block(persona: str, setting: str) -> str:
    """Rol suhbat sahnasi — AI kim va qayerda.

    Rejim fayli "roldan chiqma" deydi, bu blok esa QAYSI rol ekanini aytadi.
    Ikkisi birga bo'lgandagina o'quvchi ofitsiant bilan gaplashayotgandek
    his qiladi, "mashq qilayotgan AI" bilan emas.
    """
    lines = ["SCENE — you are not an assistant here, you are this person:"]
    if persona:
        lines.append(f"- You are: {persona}.")
    if setting:
        lines.append(f"- Where and when: {setting}.")
    lines.append(
        "- Open the session IN CHARACTER with the one line this person would "
        "really say first — a greeting from behind the counter, from the "
        "driver's seat, from across the desk. No introduction, no explanation "
        "of the exercise."
    )
    lines.append(
        "- Everything around you is real to you: other customers, the noise, "
        "the queue, the clock. Mention it when it matters, briefly."
    )
    return "\n".join(lines)


def _explanation_language_block(language: str) -> str:
    """Xato NIMA UCHUN xato — o'quvchining o'z tilida, va qayta aytirish.

    Nega kerak. A1 o'quvchi tuzatishni inglizcha eshitsa, u tuzatish ekanini
    ham anglamaydi: "you need 'am'" uning uchun shunchaki yana bir inglizcha
    gap. Tushuntirish o'z tilida bo'lsa, xato AYNAN nimada ekani bir marta
    yetib boradi.

    Nega faqat tushuntirish. Suhbatning o'zi — savol, reaksiya, to'g'ri gap —
    inglizcha qoladi. Aks holda o'quvchi ingliz tilini tinglashdan voz kechadi
    va sessiya o'zbekcha suhbatga aylanadi.

    Nega qayta aytirish. Tuzatishni ESHITISH bilan uni AYTISH o'rtasida katta
    farq bor: mashq faqat ikkinchisida bo'ladi. Shuning uchun tuzatishdan keyin
    model to'xtaydi va o'quvchi o'sha gapni o'zi aytadi.
    """
    name, described = translate.TARGETS.get(language) or translate.TARGETS[translate.DEFAULT_TARGET]
    return (
        "EXPLANATION LANGUAGE:\n"
        f"- The learner's own language is {name}. When you correct a mistake, the "
        f"part that explains WHAT was wrong is spoken in {described} — a short, "
        "plain sentence, the way you would say it to a friend.\n"
        "- Everything else stays English: your questions, your reactions, and "
        "the corrected sentence itself. Never translate the corrected sentence "
        f"and never hold the conversation in {name}.\n"
        "- Then have them say it. After the corrected sentence, ask them in "
        f"{name} to say it once themselves, stop, and WAIT for them to speak. "
        "Do not ask a new question in that turn, and do not answer for them.\n"
        "- When they say it right, one short warm English word is enough, then "
        "carry straight on with your next question.\n"
        "- A clean sentence gets none of this — no explanation, no repeating. "
        f"Never speak {name} when there is nothing to correct.\n"
        "- Example shape, with the explanation in the learner's language and "
        'everything else in English: "<explanation of the missing word>. I AM '
        'from Uzbekistan. <ask them to say it>"'
    )


def _placement_ladder_block(questions: list[str], declared_level: str, background: str) -> str:
    """Daraja aniqlash uchun zinapoya + o'quvchi o'zi aytgan ma'lumot.

    Nega ro'yxat SKRIPT emas. Savollarni ketma-ket o'qib berish darajani
    o'lchamaydi — u faqat o'quvchining sabrini o'lchaydi. O'lchov chegara
    QAYERDA ekanini topishdan iborat, ya'ni model muvaffaqiyatda yuqoriga,
    qiynalganda pastga yurishi kerak.

    Nega o'quvchi aytgani ham beriladi. "O'zini intermediate deydi" degan
    ma'lumot bilan model o'rtadan boshlaydi va taxmin to'g'rimi yoki yo'qmi
    ikki-uch navbatda bilinadi. Busiz har sessiya eng oson savoldan boshlanib,
    kuchli o'quvchining yarim vaqti behuda ketardi. Bu TAXMIN, dalil emas —
    xulosani o'lchov chiqaradi (§placement.py).
    """
    numbered = chr(10).join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    parts = [
        "PLACEMENT LADDER — easiest first. Climb it, do not read it:",
        numbered,
    ]
    said = []
    if declared_level:
        said.append(f"they describe their own English as: {declared_level}")
    if background:
        said.append(f'in their words: "{background}"')
    if said:
        parts.append(
            "WHAT THE LEARNER SAID ABOUT THEMSELVES — " + "; ".join(said) + ".\n"
            "Use it to choose where on the ladder to START, and nothing else. "
            "It is what they think, not what is true: learners routinely put "
            "themselves two steps too high or too low. Never repeat it back to "
            "them, never mention it, and drop it the moment their own sentences "
            "tell you otherwise."
        )
    return chr(10).join(parts)


def _video_shadowing_block() -> str:
    """Video bilan shadowing: gapni VIDEO aytadi, AI emas."""
    return (
        "RECORDING MODE — the learner is copying a recording, not you:\n"
        "- The lines come from a video the learner watches and hears. NEVER "
        "say a line yourself and never read the list out loud.\n"
        "- After each attempt a direction arrives with one short sentence of "
        "feedback. Say exactly that sentence, nothing else, and stop.\n"
        "- Between attempts stay silent. The learner is watching and "
        "repeating; your voice on top of the recording ruins the exercise.\n"
        "- Never start a conversation, never ask questions about the lines."
    )


def build_system_prompt(
    *,
    mode: str,
    register: int,
    target_structure: str,
    topic_title_en: str = "",
    focus_phrase: str = "",
    persona: str = "",
    setting: str = "",
    has_media: bool = False,
    chunks: list[dict] | None = None,
    spaced_repetition_block: str = "",
    questions: list[str] | None = None,
    learner_language: str = "uz",
    declared_level: str = "",
    learning_background: str = "",
) -> str:
    """Sessiya uchun to'liq system prompt.

    Savollar matni faqat `adaptive_conversation` rejimida kiritiladi (GOALS
    ro'yxati sifatida); qolgan rejimlarda model oldinga sakramasligi uchun
    savollar promptga tushmaydi (§5.2.3).
    """
    parts = [_read("base.md")]

    mode_text = _read(f"modes/{mode}.md")
    if not mode_text:
        raise ValueError(f"'{mode}' rejimi uchun prompt fayli yo'q")
    parts.append(mode_text)

    # Daraja fayli yo'q: AI o'quvchi qanday gapirsa shunday gapiradi (§adaptive).
    parts.append(adaptive.register_block(register))

    # Daraja aniqlashda mavzu ham, maqsad struktura ham YO'Q: savol o'quvchi
    # nimani biladi degan savol, "shu strukturani ishlatdimi" degan savol emas.
    # `target_structure` bu yerda texnik qiymat (`placement_probe`) — u promptga
    # tushsa model uni dars mavzusi deb olib, o'lchovni buzadi.
    is_placement = mode == SessionMode.PLACEMENT

    topic_lines = [
        "TOPIC FOCUS:",
        f"- The target structure for this session is: {target_structure}.",
        "- Every bank question is designed to make the learner produce it.",
        "- Do not name the structure or explain it. Just keep the conversation "
        "on questions that require it.",
        "- This holds however simply or however fluently the learner speaks. "
        "Matching their level changes the words you use, never the structure "
        "their answer has to contain.",
    ]
    if topic_title_en:
        topic_lines.insert(1, f"- Theme: {topic_title_en}.")
    if chunks:
        phrases = ", ".join(f'"{c["text"]}"' for c in chunks[:6])
        topic_lines.append(
            f"- Useful phrases the learner is learning: {phrases}. Use them "
            "naturally so the learner hears them, but do not drill them."
        )
    if not is_placement:
        parts.append("\n".join(topic_lines))

    # Ibora yo'nalishi: fokus grammatik shaklning USTIGA qo'shiladi.
    if focus_phrase:
        parts.append(_phrase_focus_block(focus_phrase))

    if mode == SessionMode.ROLEPLAY and (persona or setting):
        parts.append(_scene_block(persona, setting))

    if mode == SessionMode.SHADOWING and has_media:
        parts.append(_video_shadowing_block())

    # Shadowing va rol suhbat ham erkin oqim: savol banki GOALS bo'lib kiradi,
    # tuzatishni esa rejim faylining o'zi boshqaradi.
    is_free_flow = mode in FREE_FLOW_MODES

    # Video bilan shadowingda GOALS ro'yxati BERILMAYDI: ro'yxatda gaplarning
    # o'zi turadi va model ularni ovoz chiqarib o'qib yuboradi — o'quvchi esa
    # videoni emas, AI ni takrorlab qoladi. Gaplarni klient boshqaradi.
    reads_from_recording = mode == SessionMode.SHADOWING and has_media
    if is_placement:
        if questions:
            parts.append(_placement_ladder_block(questions, declared_level, learning_background))
    elif is_free_flow and questions and not reads_from_recording:
        parts.append(_session_goals_block(questions, target_structure))

    # Tuzatishni KIM topadi — shu yerda hal bo'ladi.
    #
    # Skript rejimlarida coach topadi va DIRECTOR uzatadi: u yerda navbat
    # baholanmaguncha model javob bermaydi, ya'ni kutish o'rinli.
    #
    # Erkin suhbatda model O'ZI topadi va o'sha zahoti aytadi. Baholash kritik
    # yo'ldan olib tashlangan (§consumer._close_turn_live_first) — DIRECTOR ni
    # kutib turish suhbatni har navbatda 2 s jim qoldirardi, ya'ni "jonli
    # suhbat" degan narsa yo'qolardi. Coach hamon ishlaydi, lekin fonda: uning
    # natijasi ovozga emas, EKRANGA chiqadi.
    #
    # Shadowing bundan tashqarida: u yerda grammatika tuzatilmaydi, DIRECTOR
    # bitta xulosa jumlasini beradi (§_video_shadowing_block).
    #
    # Daraja aniqlashda ham yo'q, va bu qat'iy: tuzatish O'LCHOVNI o'zgartiradi.
    # O'quvchi tuzatilgan gapni qaytarib aytadi, keyingi javobi esa o'sha
    # tuzatishga tayanadi — natijada o'lchov o'quvchi nimani bilganini emas,
    # AI nechta gapni tuzatib berganini ko'rsatadi. Bir martalik o'lchov esa
    # toza bo'lishi kerak (§modes/placement.md).
    if is_placement:
        pass
    elif not is_free_flow:
        parts.append(_read("correction_policy.md"))
    elif mode != SessionMode.SHADOWING:
        parts.append(_read("self_correction.md"))
        # Tushuntirish o'quvchi tilida — lekin faqat suhbat rejimida.
        #
        # Rol suhbatda yo'q: ofitsiant yoki shifokor birdan o'zbekchaga o'tib
        # grammatika tushuntirsa, sahna butunlay quriydi — u yerda mashqning
        # o'zi VAZIYAT ichida qolishdan iborat.
        if mode == SessionMode.ADAPTIVE_CONVERSATION:
            parts.append(_explanation_language_block(learner_language))

    # §5.2.5 — spaced repetition kiritmasi suhbat rejimlarida. Drill'da yo'q:
    # u yerda savol ketma-ketligi qat'iy, model o'tgan xatoga burila olmaydi.
    if spaced_repetition_block and (
        mode == SessionMode.GUIDED_CONVERSATION or mode in FREE_FLOW_MODES
    ):
        parts.append("PAST MISTAKES:\n" + spaced_repetition_block)

    if is_placement:
        parts.append(
            "FLOW: Say hello in one short, warm sentence and ask the first "
            "question from the bottom of the ladder. Then keep going, one "
            "question at a time, until the system ends the session."
        )
    elif is_free_flow:
        parts.append(
            "FLOW: Greet the learner in one short sentence, ask how they are, "
            "then start working through the goals. After that, keep the "
            "conversation alive on this theme until a direction tells you the "
            "session is over. The clock is the system's job, not yours."
        )
    else:
        parts.append(
            "FLOW: The first question will arrive in a DIRECTOR message. Greet the "
            "learner in one short sentence, then ask it."
        )

    return "\n\n".join(p for p in parts if p)


def prompt_fingerprint(prompt: str) -> str:
    """Log uchun qisqa hash — promptning aynan qaysi variantini ko'rish uchun."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]
