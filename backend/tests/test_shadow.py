"""Shadowing baholash (§apps/practice/shadow.py).

Bu yerda o'lchanadigan narsalar tekshiriladi: so'zlar, sur'at, ball va
xulosa matni. Talaffuz izohi modelniki — u yiqilganda ekran bo'sh
qolmasligi tekshiriladi, izohning MAZMUNI emas.
"""

import pytest
from django.test import override_settings

from apps.practice import shadow

LINE = "I'm looking forward to seeing you."


def test_exact_repeat_scores_full():
    score = shadow.compare(
        LINE, "I'm looking forward to seeing you.", spoken_ms=2000, played_ms=2000
    )
    assert score.word_accuracy == 1.0
    assert score.tempo_label == "good"
    assert score.score == 100
    assert score.missed == []


def test_missing_word_is_named():
    score = shadow.compare(LINE, "I'm looking forward seeing you.", spoken_ms=2000, played_ms=2000)
    assert "to" in score.missed
    assert score.score < 100


def test_extra_word_is_named():
    score = shadow.compare(
        LINE, "I'm really looking forward to seeing you.", spoken_ms=2200, played_ms=2000
    )
    assert "really" in score.extra


def test_saying_the_contraction_in_full_is_flagged_but_not_a_missing_word():
    """Shadowingda "I am" — xato emas, lekin MAQSAD qisqartma edi."""
    score = shadow.compare(
        LINE, "I am looking forward to seeing you.", spoken_ms=2100, played_ms=2000
    )
    assert score.contractions_lost == ["i'm"]
    # Ma'no bo'yicha to'liq mos: so'z tushib qolmagan.
    assert score.missed == []
    assert score.word_accuracy == 1.0


def test_tempo_uses_the_video_clip_when_there_is_one():
    score = shadow.compare(LINE, LINE, spoken_ms=4000, clip_start_ms=1000, clip_end_ms=3000)
    assert score.reference_ms == 2000
    assert score.tempo == 2.0
    assert score.tempo_label == "too_slow"


def test_tempo_falls_back_to_measured_playback():
    score = shadow.compare(LINE, LINE, spoken_ms=1000, played_ms=2500)
    assert score.reference_ms == 2500
    assert score.tempo_label == "too_fast"


@override_settings(SHADOW_REFERENCE_WPM=150)
def test_tempo_estimate_when_nothing_was_measured():
    """Video ham, o'lchov ham yo'q — etalon gapning tabiiy uzunligidan."""
    score = shadow.compare("one two three", "one two three", spoken_ms=1200)
    assert score.reference_ms == 1200  # 3 so'z / 150 wpm = 1.2 s
    assert score.tempo_label == "good"


def test_no_recording_means_words_only():
    score = shadow.compare(LINE, LINE)
    assert score.tempo_label == "unknown"
    assert score.score == 100  # sur'at o'lchanmagan — ball faqat so'zlardan


def test_completely_different_sentence_scores_low():
    score = shadow.compare(LINE, "The weather is very cold today.", spoken_ms=2000, played_ms=2000)
    assert score.score < 40


def test_silence_scores_zero():
    score = shadow.compare(LINE, "", spoken_ms=0, played_ms=2000)
    assert score.word_accuracy == 0.0
    assert score.score == 0


# --- xulosa matni ---------------------------------------------------------


@pytest.mark.parametrize("language", ["uz", "ru"])
def test_fallback_note_is_written_in_the_learner_language(language):
    score = shadow.compare(LINE, "I'm looking forward seeing you.", spoken_ms=2000, played_ms=2000)
    note = shadow.fallback_note(score, language)
    assert note
    assert note == shadow.FALLBACK[language]["missed"].format(words="to")


def test_fallback_note_names_tempo_when_words_are_right():
    score = shadow.compare(LINE, LINE, spoken_ms=5000, played_ms=2000)
    assert shadow.fallback_note(score, "uz") == shadow.FALLBACK["uz"]["too_slow"]


def test_fallback_note_praises_a_clean_repeat():
    score = shadow.compare(LINE, LINE, spoken_ms=2000, played_ms=2000)
    assert shadow.fallback_note(score, "uz") == shadow.FALLBACK["uz"]["great"]


@pytest.mark.asyncio
@override_settings(SHADOW_PRONUNCIATION_ENABLED=False)
async def test_pronunciation_call_is_skipped_when_disabled():
    note, usage = await shadow.pronunciation_note(b"\x00" * 32000, LINE, "uz")
    assert note == ""
    assert usage == {}


@pytest.mark.asyncio
async def test_pronunciation_call_is_skipped_for_a_tiny_clip():
    note, _ = await shadow.pronunciation_note(b"\x00" * 100, LINE, "uz")
    assert note == ""
