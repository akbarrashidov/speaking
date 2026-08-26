"""Daraja aniqlash suhbatining XULOSASI — sof mantiq, LLM yo'q.

Bir martalik suhbatdan keyin ikki qaror chiqadi:

1. `register` — AI keyingi sessiyalarda qanday gapiradi (§adaptive.py).
2. `back_to_start` — o'quvchi boshlang'ich qismga qaytariladimi.

Ikkalasi ham suhbat DAVOMIDA yig'ilgan o'lchovdan chiqadi: coach har navbatda
`fluency` va verdikt qaytargan, ya'ni bu yerda yangi chaqiruv kerak emas.

Nega alohida modul. Bu qoidalar o'quvchi uchun eng qimmat qaror: noto'g'ri
bo'lsa u yo o'ziga juda oson, yo umuman tushunarsiz kursga tushib qoladi.
Shuning uchun ular bitta joyda, sof funksiyada va testlar bilan qotirilgan —
`tasks.py` ichidagi shartlar orasida emas.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import adaptive

# Shundan kam baholangan navbat — o'lchov emas. Ikki gapdan daraja chiqarib
# bo'lmaydi, va aynan shu holat eng ko'p uchraydi: o'quvchi uyalib, jim o'tiradi.
# Bunday sessiya "past daraja" degan xulosa emas — MA'LUMOT YO'Q degani, va
# ikkalasida ham to'g'ri javob bitta: boshidan boshlash.
MIN_GRADED_TURNS = 3

# Coach verdikti (§coach.VALID_VERDICTS). Faqat shu biri "to'g'ri" hisoblanadi.
CORRECT = "correct"

# Shu registr va pastda — boshlang'ich qism. 1 = parcha gaplar: bunday o'quvchi
# o'rtadan boshlansa har darsda yo'qolib qoladi.
BEGINNER_REGISTER = 1

# Birinchi urinishdagi aniqlik shundan past bo'lsa — ravonlikdan qat'i nazar
# boshlang'ichga. Ravon gapirish tushunish demas: gapi uzun, lekin har gapi
# xato bo'lgan o'quvchiga tezlashtirish yordam bermaydi (§adaptive.RAISE_MIN_ACCURACY).
LOW_ACCURACY = 0.4

# Aniqlik past bo'lganda registr shundan yuqoriga chiqmaydi.
CAPPED_REGISTER = 2


@dataclass
class PlacementOutcome:
    register: int
    back_to_start: bool
    reason: str
    graded_turns: int
    avg_fluency: float
    accuracy: float = 0.0

    def to_dict(self) -> dict:
        return {
            "register": self.register,
            "back_to_start": self.back_to_start,
            "reason": self.reason,
            "graded_turns": self.graded_turns,
            "avg_fluency": round(self.avg_fluency, 2),
            "accuracy": round(self.accuracy, 2),
        }


def outcome(coach_records: list[dict]) -> PlacementOutcome:
    """Coach yozuvlari → daraja qarori.

    Ravonlik ham, aniqlik ham AYNAN SHU ro'yxatdan olinadi. Ilgari aniqlik
    tashqaridan (`metrics.first_attempt_accuracy`) berilardi va ikkita manba
    bir-biriga zid kelishi mumkin edi: coach oltita gapni baholagan, lekin
    `Evaluation` yozuvlari yetib kelmagan bo'lsa, aniqlik 0 chiqib, ravon
    gapirgan o'quvchi "ko'p xato qiladi" degan xulosa olardi. Bitta manba —
    bitta haqiqat.
    """
    graded = [r for r in coach_records if str(r.get("utterance") or "").strip()]
    if len(graded) < MIN_GRADED_TURNS:
        # Gapirmadi yoki juda kam gapirdi. Bu past daraja emas, o'lchov yo'q —
        # lekin qaror bir xil: eng oddiy joydan boshlanadi.
        return PlacementOutcome(
            register=adaptive.MIN_REGISTER,
            back_to_start=True,
            reason="not_enough_speech",
            graded_turns=len(graded),
            avg_fluency=0.0,
        )

    fluencies = [float(r.get("fluency") or 0) for r in graded]
    avg_fluency = sum(fluencies) / len(fluencies)
    accuracy = sum(1 for r in graded if r.get("verdict") == CORRECT) / len(graded)
    # Yarimni yuqoriga — `adaptive.next_register` bilan bir xil yaxlitlash.
    register = adaptive.clamp(int(avg_fluency + 0.5))

    reason = "measured"
    if accuracy < LOW_ACCURACY:
        register = min(register, CAPPED_REGISTER)
        reason = "many_mistakes"
    elif register <= BEGINNER_REGISTER:
        reason = "low_register"

    return PlacementOutcome(
        register=register,
        back_to_start=register <= BEGINNER_REGISTER or accuracy < LOW_ACCURACY,
        reason=reason,
        graded_turns=len(graded),
        avg_fluency=avg_fluency,
        accuracy=accuracy,
    )
