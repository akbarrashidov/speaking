"""§5.2 — system prompt yig'ilishi."""

import pytest

from apps.practice.prompts import PROMPT_VERSION, build_system_prompt


def build(mode="anticipation_drill", **kwargs):
    defaults = {
        "mode": mode,
        "register": 2,
        "target_structure": "past_simple_affirmative",
        "topic_title_en": "Yesterday",
    }
    return build_system_prompt(**{**defaults, **kwargs})


def flat(mode="anticipation_drill", **kwargs):
    """Prompt bir qatorga keltirilgan holda — iboralar satrga bo'linib ketmasin."""
    return " ".join(build(mode, **kwargs).split())


def test_prompt_contains_hard_rules():
    prompt = flat()
    assert "conversation partner who also corrects" in prompt
    # Tuzatadi, lekin dars o'tmaydi: qoida nomlanmaydi, atama ishlatilmaydi.
    assert "never use grammar words" in prompt
    assert "you say plainly what was wrong" in prompt


def test_prompt_establishes_the_director_contract():
    """Live modeli backend ko'rsatmasini ovoz chiqarib o'qib yubormasligi shart."""
    prompt = flat()
    assert "[DIRECTOR" in prompt
    assert "NEVER speak a director message" in prompt
    # Kontrakt real regressiyadan keyin kuchaytirildi: model direktivni
    # o'quvchi gapi deb qabul qilib, uni o'qib yuborgan edi.
    assert "never something the learner said" in prompt
    assert "check your own sentence" in prompt


def test_prompt_no_longer_mentions_the_removed_tool():
    """Faza 3 — baholash Live'dan olib tashlandi, tool e'lon qilinmaydi."""
    assert "evaluate_answer" not in build()


def test_prompt_contains_mode_and_register_blocks():
    drill = build("anticipation_drill")
    assert "MODE: anticipation drill" in drill
    # Daraja bloki yo'q — uning o'rnida ko'zgu qoidasi (§adaptive.py).
    assert "LEARNER LEVEL" not in drill
    assert "MATCH THE LEARNER, TURN BY TURN" in drill

    guided = build("guided_conversation", register=4)
    assert "MODE: guided conversation" in guided
    assert "full natural pace" in guided


def test_register_block_tells_the_model_to_follow_the_learner():
    """Daraja tanlanmaydi: AI o'quvchi qanday gapirsa, shunday gapiradi."""
    simple = " ".join(build(register=0).split())
    assert "simplest English" in simple
    assert "never above it" in simple
    # Registr faqat TILNI o'zgartiradi, mashqni emas.
    assert "never the structure" in simple


def test_prompt_contains_target_structure_but_no_question_list():
    prompt = build()
    assert "past_simple_affirmative" in prompt
    # §5.2.3 — savollar DIRECTOR orqali bittalab beriladi.
    assert "question bank:" not in prompt.lower()


def test_correction_policy_is_always_included():
    assert "CORRECTION POLICY" in build()


def test_chunks_are_mentioned_when_present():
    prompt = build(chunks=[{"text": "to be honest", "translation_uz": "rostini aytsam"}])
    assert "to be honest" in prompt


def test_spaced_repetition_is_injected_into_conversation_modes_only():
    """§5.2.5 — drill'da savol ketma-ketligi qat'iy, o'tgan xatoga burilib bo'lmaydi."""
    block = "This learner has previously made these mistakes:\n- said X"

    guided = build("guided_conversation", spaced_repetition_block=block)
    assert "PAST MISTAKES" in guided

    free = build(
        "adaptive_conversation",
        questions=["What is your job?"],
        spaced_repetition_block=block,
    )
    assert "PAST MISTAKES" in free

    drill = build("anticipation_drill", spaced_repetition_block=block)
    assert "PAST MISTAKES" not in drill


# --- adaptive_conversation ------------------------------------------------


def adaptive(**kwargs):
    defaults = {
        "questions": ["What is your job?", "What did you do yesterday?"],
    }
    return build("adaptive_conversation", **{**defaults, **kwargs})


def test_adaptive_mode_block_is_included():
    prompt = adaptive()
    assert "MODE: adaptive conversation" in prompt
    assert "there is no script" in prompt


def test_adaptive_prompt_lists_the_questions_as_numbered_goals():
    """Savollar bu yerda skript emas — model ularni moslab qayta yozadi."""
    prompt = adaptive()
    assert "SESSION GOALS" in prompt
    assert "1. What is your job?" in prompt
    assert "2. What did you do yesterday?" in prompt
    assert "Target structure: past_simple_affirmative." in prompt


def test_adaptive_prompt_never_reasks_a_covered_goal():
    """Bitta to'liq javob bir nechta maqsadni yopadi — ular qayta so'ralmaydi."""
    prompt = " ".join(adaptive().split())
    assert "A goal is covered the moment the learner tells you the answer" in prompt
    assert "One full answer can cover three goals at once" in prompt
    assert "Never ask something they have already answered" in prompt


def test_adaptive_prompt_excludes_the_correction_policy():
    """Rejim faylining o'z CORRECTIONS bo'limi bor va u siyosatga zid."""
    assert "CORRECTION POLICY" not in adaptive()


def test_adaptive_flow_does_not_wait_for_a_director_question():
    prompt = " ".join(adaptive().split())
    assert "ask how they are, then start working through the goals" in prompt
    assert "The first question will arrive in a DIRECTOR message" not in prompt


def test_other_modes_keep_their_question_free_prompt():
    """Regressiya: GOALS bloki faqat adaptive rejimga tegishli (§5.2.3)."""
    for mode in ("anticipation_drill", "guided_conversation"):
        prompt = build(mode, questions=["What is your job?"])
        assert "SESSION GOALS" not in prompt
        assert "What is your job?" not in prompt
        assert "CORRECTION POLICY" in prompt


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        build("free_conversation")


def test_prompt_version_is_recorded():
    assert PROMPT_VERSION.startswith("v")


def test_adaptive_prompt_forbids_ending_the_conversation():
    """Bank 2-3 savoldan iborat bo'lishi mumkin — ro'yxat tugashi sessiya emas.

    Real regressiya: model GOALS tugashi bilan "It was nice talking with you!"
    deb sessiyani o'zi yopib qo'ygan edi.
    """
    prompt = " ".join(adaptive().split())
    assert "never a reason to end or wind down the session" in prompt
    assert "NEVER END THE CONVERSATION" in prompt
    assert "Never say goodbye" in prompt
    assert "The clock is the system's job, not yours." in prompt


def test_adaptive_prompt_requires_building_on_the_last_answer():
    """O'quvchi shikoyati: gapimni tahlil qilmayapti, bir xil savol beryapti."""
    prompt = " ".join(adaptive().split())
    assert "BUILD ON WHAT THEY JUST SAID" in prompt
    assert "Never ask something they have already answered" in prompt
    assert "it is the wrong question" in prompt


def test_adaptive_prompt_keeps_questions_inside_the_topic():
    """Erkin suhbat "istalgan suhbat" degani emas — bitta struktura, bitta mavzu."""
    prompt = " ".join(adaptive().split())
    assert "STAY INSIDE THE TOPIC" in prompt
    assert "impossible to answer correctly without the target structure" in prompt
    assert "bring it back with a question that needs the target structure" in prompt


def test_adaptive_prompt_tells_the_model_not_to_read_the_options():
    """Variantlar ekranda — ovozda aytilsa, o'quvchi gapirmay tinglab qoladi."""
    prompt = " ".join(adaptive().split())
    assert "two or three possible answers on the learner's screen" in prompt
    assert "never read those answers out loud" in prompt


def test_placement_prompt_makes_the_model_pull_speech_out():
    """O'lchov uchun NUTQ kerak, o'quvchi esa o'z-o'zidan gapirmaydi.

    Bir so'zli javob hech narsani o'lchamaydi, jim sessiya esa umuman hech
    narsani. Shu bois gapirtirish bu rejimda xushmuomalalik emas — ishning
    o'zi: promptda buni majburlaydigan qoidalar bo'lishi kerak.
    """
    prompt = " ".join(flat("placement").split())
    assert "Getting them to talk is the job".upper() in prompt.upper()
    assert "Never accept a one-word answer as an answer" in prompt
    # Davomi AYNAN o'quvchi aytgan narsa haqida bo'ladi — eng oson joy.
    assert "Ask about the thing they already mentioned" in prompt
    # Kim ko'p gapirayotgani o'lchov: model gapirsa o'lchov yo'q.
    assert "theirs should be longer than yours" in prompt
    # Jim qolganda: sodda savol yoki ikki tomonlama tanlov, javobni aytmaslik.
    assert "offer a two-way choice" in prompt
    assert "Never answer for them" in prompt


def test_placement_prompt_never_calls_itself_a_test():
    prompt = " ".join(flat("placement").split())
    for word in ("exam", "assessment", "score"):
        assert f'"{word}"' in prompt, "taqiqlangan so'zlar ro'yxati buzilgan"
    assert "Never explain why you are asking" in prompt


def test_adaptive_prompt_corrects_every_mistake_out_loud():
    """Ekrandagi diff gapirayotgan o'quvchiga ko'rinmaydi — xato ovozda ham."""
    prompt = " ".join(adaptive().split())
    assert "A mistake you let pass is a mistake they keep for years" in prompt
    # Tuzatish javobning O'ZIDA — alohida, kechikkan navbat emas.
    assert "in the SAME breath as your reply" in prompt


def test_adaptive_prompt_finds_the_mistake_itself():
    """Erkin suhbatda model DIRECTOR ni kutmaydi — xatoni o'zi topadi.

    Baholash kritik yo'ldan olib tashlangan (§settings.LIVE_FIRST_ENABLED):
    ko'rsatma kutib turish har navbatdan keyin ~2 s jimlik degani edi. Shu
    bois eski kontrakt ("o'zboshimchalik bilan tuzatma") bu yerda BO'LMASLIGI
    kerak — aks holda model xatoni ko'ra-bila jim o'tib ketadi.
    """
    prompt = " ".join(adaptive().split())
    assert "You heard the learner with your own ears" in prompt
    assert "Do not wait." in prompt
    assert "without a direction, do not stop to correct anything" not in prompt
    # Ekrandagi ro'yxat modelniki emas — o'qib berilmaydi.
    assert "never read it out" in prompt


def test_adaptive_prompt_says_what_was_wrong():
    """Faqat to'g'ri shaklni qaytarish yetarli emas — qaysi so'z buzilgani aytiladi."""
    prompt = " ".join(adaptive().split())
    assert "which word was wrong or missing" in prompt
    # Namuna: so'zning o'zi ko'rsatiladi, qoida nomlanmaydi.
    assert "you need 'am'" in prompt


def test_the_explanation_goes_in_the_learners_own_language():
    """Xato o'quvchining o'z tilida tushuntiriladi, gap esa inglizcha qoladi.

    A1 o'quvchi inglizcha tuzatishni tuzatish deb ham anglamaydi: "you need
    'am'" uning uchun shunchaki yana bir inglizcha gap. Ammo suhbatning O'ZI
    o'zbekchaga o'tib ketmasligi kerak — aks holda sessiya ingliz tilida
    gapirish mashqi bo'lishdan to'xtaydi.
    """
    prompt = flat("adaptive_conversation")
    assert "EXPLANATION LANGUAGE:" in prompt
    assert "The learner's own language is Uzbek" in prompt
    assert "Everything else stays English" in prompt
    assert "Never translate the corrected sentence" in prompt
    # Toza gapda o'zbekcha umuman ishlatilmaydi.
    assert "Never speak Uzbek when there is nothing to correct" in prompt

    russian = flat("adaptive_conversation", learner_language="ru")
    assert "The learner's own language is Russian" in russian
    assert "ask them in Russian" in russian
    assert "ask them in Uzbek" not in russian


def test_a_corrected_sentence_is_handed_back_to_the_learner():
    """Tuzatishni eshitish uni aytishning o'rnini bosmaydi — qayta aytiriladi."""
    prompt = flat("adaptive_conversation")
    assert "ask them in Uzbek to say it once themselves, stop, and WAIT" in prompt
    assert "Do not ask a new question in that turn" in prompt
    # Qotib qolgan o'quvchi haqidagi qoida bilan aralashmasligi kerak.
    assert "It is not about a correction" in prompt


def test_roleplay_keeps_the_scene_and_explains_in_english():
    """Rol suhbatda ofitsiant o'zbekcha grammatika tushuntirmaydi — sahna quriydi."""
    prompt = flat("roleplay", persona="a waiter", setting="a cafe")
    # Tuzatish bor — lekin tushuntirish tili bloki yo'q.
    assert "You heard the learner with your own ears" in prompt
    assert "EXPLANATION LANGUAGE:" not in prompt


def test_adaptive_prompt_still_forbids_teaching_grammar():
    """Tuzatish ko'paydi — dars bo'lib ketmasligi shart."""
    prompt = " ".join(adaptive().split())
    assert "never name a grammar rule, never use grammar words" in prompt
    assert 'Never say the word "mistake"' in prompt
    assert "One correction per turn" in prompt
