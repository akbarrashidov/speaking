"""Sessiya state machine (§4.4) — sof logika, I/O yo'q.

Haqiqiy holat backend'da yashaydi (Redis), hech qachon LLM promptida emas.
Bu modul Django'ga bog'liq emas, shuning uchun to'g'ridan-to'g'ri unit-test qilinadi.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Phase(StrEnum):
    IDLE = "idle"
    ASKING = "asking"
    LISTENING = "listening"
    MODEL_ANSWER = "model_answer"
    ENDED = "ended"


class Action(StrEnum):
    ASK_QUESTION = "ask_question"
    RETRY = "retry"
    CLARIFY = "clarify"  # unintelligible — alohida signal (§4.5)
    GIVE_MODEL_ANSWER = "give_model_answer"
    NEXT_QUESTION = "next_question"
    END_SESSION = "end_session"
    # Hech qanday direktiv yuborilmaydi — suhbat oqimini Live o'zi boshqaradi
    # (adaptive_conversation). Baholash faqat statistika uchun yoziladi.
    NO_OP = "no_op"


class Verdict(StrEnum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    OFF_TOPIC = "off_topic"
    UNINTELLIGIBLE = "unintelligible"


VALID_VERDICTS = {v.value for v in Verdict}

MAX_ATTEMPTS_BEFORE_MODEL = 2  # §4.4: hech qachon 3+ urinish


@dataclass
class QuestionRecord:
    """Bitta savol bo'yicha natija — post-session pipeline uchun manba."""

    question_id: int
    attempts: int = 0
    correct: bool = False
    first_attempt_correct: bool = False
    recovered_after_model: bool = False
    model_answer_given: bool = False
    severe_error: bool = False
    error_types: list[str] = field(default_factory=list)
    utterances: list[str] = field(default_factory=list)


@dataclass
class Decision:
    """Backend'ning modelga qaytaradigan ko'rsatmasi (§4.5 tool response)."""

    action: Action
    payload: dict[str, Any] = field(default_factory=dict)

    def as_tool_response(self) -> dict[str, Any]:
        return {"next_action": self.action.value, "payload": self.payload}


@dataclass
class SessionState:
    session_id: str
    mode: str
    question_ids: list[int]
    max_questions: int = 10
    q_index: int = -1  # hali birinchi savol berilmagan
    attempt: int = 0  # joriy savol bo'yicha baholangan urinishlar soni
    model_answer_given: bool = False
    phase: str = Phase.IDLE.value
    asked_total: int = 0
    # Baholangan navbatlar soni. `asked_total` dan farqi: erkin suhbatda savol
    # "berilmaydi" (bank GOALS ro'yxati), shuning uchun u yerda registr
    # moslashuvining yagona o'lchov birligi shu hisoblagich (`adaptive.py`).
    evaluated_total: int = 0
    correct_total: int = 0
    first_attempt_correct: int = 0
    severe_errors: int = 0
    records: dict[str, dict] = field(default_factory=dict)
    injected_error_log_ids: list[int] = field(default_factory=list)
    ended_reason: str = ""

    # --- coach uchun kontekst (§Faza 3) ---
    # AI suhbat registri 0..4 — o'quvchi qanday gapirsa, shunday (`adaptive.py`).
    # Sessiya foydalanuvchining o'tgan registridan boshlanadi.
    register: int = 2
    # O'quvchi javobida ALLAQACHON yopilgan maqsad-savollar. Erkin suhbatda
    # savollar skript emas, ro'yxat: o'quvchi bitta javobda uchtasini birdan
    # yopib yuborishi mumkin va o'shanda ularni qayta so'rash — suhbatni
    # so'roqqa aylantiradi (§consumer._open_goals).
    covered_question_ids: list[int] = field(default_factory=list)
    # Ketma-ket necha javobda target struktura ishlatilmadi — 2 dan oshsa
    # keyingi savol strukturani muqarrar qiladigan shaklga majburlanadi.
    structure_miss_streak: int = 0
    # Oxirgi xato turlari — coach takrorlanuvchi naqshni ko'rishi uchun.
    recent_error_types: list[str] = field(default_factory=list)
    # Oxirgi javoblarning ravonlik bahosi (0..4) — `adaptive.py` manbai.
    recent_fluency: list[int] = field(default_factory=list)
    # Podkaska zinapoyasi va qotib qolish hisobi (§Faza 4).
    hint_rung: int = 0
    stuck_count: int = 0

    # ---- serializatsiya -------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SessionState:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    # ---- yordamchilar ---------------------------------------------------
    @property
    def current_question_id(self) -> int | None:
        if 0 <= self.q_index < len(self.question_ids):
            return self.question_ids[self.q_index]
        return None

    @property
    def is_ended(self) -> bool:
        return self.phase == Phase.ENDED.value

    @property
    def questions_remaining(self) -> int:
        return max(0, min(len(self.question_ids), self.max_questions) - self.asked_total)

    def record_for(self, question_id: int) -> QuestionRecord:
        raw = self.records.get(str(question_id))
        if raw is None:
            rec = QuestionRecord(question_id=question_id)
            self.records[str(question_id)] = asdict(rec)
            return rec
        return QuestionRecord(**raw)

    def save_record(self, rec: QuestionRecord) -> None:
        self.records[str(rec.question_id)] = asdict(rec)

    def summary(self) -> dict:
        return {
            "questions_total": self.asked_total,
            "correct_total": self.correct_total,
            "first_attempt_correct": self.first_attempt_correct,
            "severe_errors": self.severe_errors,
        }


# ---------------------------------------------------------------------------
# Rejim strategiyalari (§4.3 — pluggable)
# ---------------------------------------------------------------------------


class ModeStrategy:
    """Rejim uchun tarmoqlanish qoidalari."""

    name = "base"
    evaluates_answers = True
    requires_followup = False

    def on_evaluation(self, state: SessionState, verdict: str, error_type: str | None):
        raise NotImplementedError


class AnticipationDrillStrategy(ModeStrategy):
    """A1 — Pimsleur uslubidagi to'liq retry → model javob → qayta savol sikli."""

    name = "anticipation_drill"

    def on_evaluation(self, state: SessionState, verdict: str, error_type: str | None):
        rec = state.record_for(state.current_question_id)
        rec.attempts = state.attempt
        if error_type:
            rec.error_types.append(error_type)

        if verdict == Verdict.CORRECT.value:
            rec.correct = True
            state.correct_total += 1
            if state.attempt == 1 and not state.model_answer_given:
                rec.first_attempt_correct = True
                state.first_attempt_correct += 1
            if state.model_answer_given:
                rec.recovered_after_model = True
            state.save_record(rec)
            return Action.NEXT_QUESTION

        # Noto'g'ri javoblar shoxobchasi.
        if state.model_answer_given:
            # Model javobdan keyingi yakuniy urinish ham muvaffaqiyatsiz (§4.4).
            rec.severe_error = True
            state.severe_errors += 1
            state.save_record(rec)
            return Action.NEXT_QUESTION

        if state.attempt >= MAX_ATTEMPTS_BEFORE_MODEL:
            rec.model_answer_given = True
            state.save_record(rec)
            return Action.GIVE_MODEL_ANSWER

        state.save_record(rec)
        return Action.CLARIFY if verdict == Verdict.UNINTELLIGIBLE.value else Action.RETRY


class GuidedConversationStrategy(ModeStrategy):
    """B1 — suhbat oqimi buzilmaydi: baholash log qilinadi, keyin follow-up.

    Tuzatish siyosati (§4.3.2): faqat tushunishga xalaqit beradigan xato recast
    bilan tuzatiladi, qolgani sessiyadan keyingi feedbackka qoladi. Drill retry
    sikli bu rejimda ishlamaydi.
    """

    name = "guided_conversation"
    requires_followup = True

    BLOCKING_ERRORS = {"unintelligible", "off_topic"}

    def on_evaluation(self, state: SessionState, verdict: str, error_type: str | None):
        rec = state.record_for(state.current_question_id)
        rec.attempts = state.attempt
        if error_type:
            rec.error_types.append(error_type)

        if verdict == Verdict.CORRECT.value:
            rec.correct = True
            state.correct_total += 1
            if state.attempt == 1:
                rec.first_attempt_correct = True
                state.first_attempt_correct += 1
            state.save_record(rec)
            return Action.NEXT_QUESTION

        if verdict == Verdict.UNINTELLIGIBLE.value and state.attempt == 1:
            state.save_record(rec)
            return Action.CLARIFY

        state.save_record(rec)
        return Action.NEXT_QUESTION


class AdaptiveConversationStrategy(ModeStrategy):
    """Erkin suhbat — state machine oqimga UMUMAN aralashmaydi.

    Savollar skript emas: ular system promptdagi SESSION GOALS ro'yxati, navbatni
    esa Live o'zi boshqaradi. Shuning uchun har baholash `NO_OP` bilan tugaydi —
    modelga hech qanday direktiv ketmaydi. Coach natijasi yo'qolmaydi: u ekranga
    `correction` eventi bo'lib chiqadi (consumer). Sessiya faqat vaqt limiti
    bilan yakunlanadi.
    """

    name = "adaptive_conversation"
    requires_followup = True

    def on_evaluation(self, state: SessionState, verdict: str, error_type: str | None):
        rec = state.record_for(state.current_question_id)
        rec.attempts += 1
        if error_type:
            rec.error_types.append(error_type)

        if verdict == Verdict.CORRECT.value:
            rec.correct = True
            state.correct_total += 1
            if state.attempt == 1:
                rec.first_attempt_correct = True
                state.first_attempt_correct += 1

        state.save_record(rec)
        # Suhbatda "qayta urinish" tushunchasi yo'q — har gap mustaqil navbat,
        # shuning uchun hisoblagich qaytariladi va keyingi gap ham birinchi
        # urinish bo'lib qoladi.
        state.attempt = 0
        return Action.NO_OP


class ShadowingStrategy(AdaptiveConversationStrategy):
    """Shadowing — oqim erkin suhbat bilan bir xil, farq faqat promptda.

    State machine bu yerda ham aralashmaydi: AI gapni aytadi, o'quvchi
    takrorlaydi, coach esa takroriy gapni baholab ekranga tuzatish chiqaradi.
    "Qayta urinish" sikli yo'q — keyingi gap o'zi yangi urinish.
    """

    name = "shadowing"


class RoleplayStrategy(AdaptiveConversationStrategy):
    """Rol suhbat — vaziyat oxirigacha olib boriladi, skript yo'q."""

    name = "roleplay"


class PlacementStrategy(AdaptiveConversationStrategy):
    """Daraja aniqlash — erkin oqim, lekin natijasi o'rganish emas, O'LCHOV.

    Strategiya erkin suhbatnikidan meros: mashina navbatga aralashmaydi, savol
    bermaydi va qayta aytirishni talab qilmaydi — bularning hammasini model
    o'zi zinapoya bo'yicha qiladi (§prompts/modes/placement.md).

    Nega baribir strategiya kerak. Baholash bu rejimda ham ishlaydi: `fluency`
    va verdikt aynan shu yerdan o'tib, sessiya oxirida xulosaga aylanadi
    (§placement.py). Strategiya bo'lmasa `sm.evaluate` yiqilib, har navbat
    baholanmay qolardi — ya'ni o'lchov umuman bo'lmasdi.
    """

    name = "placement"


STRATEGIES: dict[str, ModeStrategy] = {
    AnticipationDrillStrategy.name: AnticipationDrillStrategy(),
    GuidedConversationStrategy.name: GuidedConversationStrategy(),
    AdaptiveConversationStrategy.name: AdaptiveConversationStrategy(),
    ShadowingStrategy.name: ShadowingStrategy(),
    RoleplayStrategy.name: RoleplayStrategy(),
    PlacementStrategy.name: PlacementStrategy(),
}


def get_strategy(mode: str) -> ModeStrategy:
    try:
        return STRATEGIES[mode]
    except KeyError as exc:
        raise ValueError(f"'{mode}' rejimi MVP'da amalga oshirilmagan") from exc


# ---------------------------------------------------------------------------
# Machine — savol berish / baholash o'tishlari
# ---------------------------------------------------------------------------


def start_question(state: SessionState) -> Decision:
    """Keyingi savolga o'tadi. Bank tugasa yoki limit bo'lsa — sessiya yakuni."""
    if state.is_ended:
        return Decision(Action.END_SESSION, {"reason": state.ended_reason or "ended"})

    next_index = state.q_index + 1
    if next_index >= len(state.question_ids) or state.asked_total >= state.max_questions:
        return end(state, "completed")

    state.q_index = next_index
    state.attempt = 0
    state.model_answer_given = False
    # Yangi savol — podkaska zinapoyasi ham noldan boshlanadi (§Faza 4).
    state.hint_rung = 0
    state.stuck_count = 0
    state.asked_total += 1
    state.phase = Phase.ASKING.value
    return Decision(
        Action.ASK_QUESTION,
        {
            "question_id": state.current_question_id,
            "question_number": state.asked_total,
            "questions_remaining": state.questions_remaining,
        },
    )


def evaluate(
    state: SessionState,
    question_id: int | None,
    verdict: str,
    error_type: str | None = None,
) -> Decision:
    """`evaluate_answer` tool call'ini qayta ishlaydi va keyingi harakatni qaytaradi."""
    if state.is_ended:
        return Decision(Action.END_SESSION, {"reason": state.ended_reason or "ended"})

    if verdict not in VALID_VERDICTS:
        verdict = Verdict.UNINTELLIGIBLE.value

    current = state.current_question_id
    if current is None:
        # Model savol berilmasdan baholadi — savol berishga majburlaymiz.
        return start_question(state)

    if question_id is not None and int(question_id) != current:
        # Model boshqa savolni baholadi (oldinga sakrash urinishi) — e'tiborsiz
        # qoldiramiz va joriy savolda qolamiz.
        return Decision(
            Action.RETRY,
            {
                "question_id": current,
                "reason": "question_id_mismatch",
                "instruction": "Stay on the current question. Ask it again, exactly as given.",
            },
        )

    state.attempt += 1
    state.evaluated_total += 1
    strategy = get_strategy(state.mode)
    action = strategy.on_evaluation(state, verdict, error_type)

    if action == Action.GIVE_MODEL_ANSWER:
        state.model_answer_given = True
        state.phase = Phase.MODEL_ANSWER.value
        return Decision(Action.GIVE_MODEL_ANSWER, {"question_id": current})

    if action == Action.NEXT_QUESTION:
        return start_question(state)

    state.phase = Phase.LISTENING.value
    return Decision(action, {"question_id": current, "attempt": state.attempt})


def end(state: SessionState, reason: str) -> Decision:
    state.phase = Phase.ENDED.value
    state.ended_reason = reason
    return Decision(Action.END_SESSION, {"reason": reason, **state.summary()})
