"""Narx hisobi (Faza 0) — `apps/practice/cost.py`."""

from __future__ import annotations

import pytest

from apps.practice import cost


def usage(prompt_audio=0, prompt_text=0, resp_audio=0, resp_text=0):
    """Gemini Live `usageMetadata` shaklidagi namuna."""
    return {
        "promptTokenCount": prompt_audio + prompt_text,
        "responseTokenCount": resp_audio + resp_text,
        "totalTokenCount": prompt_audio + prompt_text + resp_audio + resp_text,
        "promptTokensDetails": [
            {"modality": "AUDIO", "tokenCount": prompt_audio},
            {"modality": "TEXT", "tokenCount": prompt_text},
        ],
        "responseTokensDetails": [
            {"modality": "AUDIO", "tokenCount": resp_audio},
            {"modality": "TEXT", "tokenCount": resp_text},
        ],
    }


class TestModalitySplit:
    def test_splits_audio_and_text(self):
        parts = cost.split_modalities(usage(prompt_audio=1000, prompt_text=200, resp_audio=500))
        assert parts == {"text_in": 200, "audio_in": 1000, "text_out": 0, "audio_out": 500}

    def test_missing_details_counts_as_audio(self):
        """Tafsilot bo'lmasa qimmatroq modalitet tanlanadi — narx kam ko'rsatilmasin."""
        parts = cost.split_modalities({"promptTokenCount": 900, "responseTokenCount": 300})
        assert parts["audio_in"] == 900
        assert parts["audio_out"] == 300
        assert parts["text_in"] == 0

    def test_detail_shortfall_goes_to_audio(self):
        raw = usage(prompt_audio=100, prompt_text=50)
        raw["promptTokenCount"] = 200  # tafsilotda ko'rsatilmagan 50 token
        parts = cost.split_modalities(raw)
        assert parts["audio_in"] == 150
        assert parts["text_in"] == 50

    def test_empty_usage(self):
        assert cost.split_modalities(None) == {
            "text_in": 0,
            "audio_in": 0,
            "text_out": 0,
            "audio_out": 0,
        }

    def test_snake_case_keys_supported(self):
        parts = cost.split_modalities(
            {
                "prompt_token_count": 400,
                "prompt_tokens_details": [{"modality": "TEXT", "token_count": 400}],
            }
        )
        assert parts["text_in"] == 400


class TestPriceResolution:
    def test_longest_prefix_wins(self, settings):
        settings.LIVE_PRICING = {
            "gemini-2.5": {"text_in": 9, "audio_in": 9, "text_out": 9, "audio_out": 9},
            "gemini-2.5-flash-native-audio": {
                "text_in": 1,
                "audio_in": 1,
                "text_out": 1,
                "audio_out": 1,
            },
            "default": {"text_in": 0, "audio_in": 0, "text_out": 0, "audio_out": 0},
        }
        prices = cost.resolve_live_prices("gemini-2.5-flash-native-audio-preview-12-2025")
        assert prices["text_in"] == 1

    def test_models_prefix_stripped(self):
        assert cost.resolve_live_prices("models/gemini-3.1-flash-live-preview") == (
            cost.resolve_live_prices("gemini-3.1-flash-live-preview")
        )

    def test_unknown_model_falls_back(self):
        assert cost.resolve_live_prices("something-else") is not None

    def test_text_model_matched_by_substring(self):
        prices = cost.resolve_text_prices("accounts/fireworks/models/gpt-oss-120b")
        assert prices["text_in"] > 0


class TestBreakdown:
    def test_live_cost_arithmetic(self, settings):
        settings.LIVE_PRICING = {
            "test-model": {
                "text_in": 1.00,
                "audio_in": 3.00,
                "text_out": 4.00,
                "audio_out": 12.00,
            },
            "default": {"text_in": 0, "audio_in": 0, "text_out": 0, "audio_out": 0},
        }
        bd = cost.live_breakdown(
            usage(prompt_audio=1_000_000, prompt_text=1_000_000, resp_audio=1_000_000), "test-model"
        )
        # 1M audio_in ($3) + 1M text_in ($1) + 1M audio_out ($12)
        assert bd.live_usd == pytest.approx(16.0)
        assert bd.total_usd == pytest.approx(16.0)

    def test_audio_seconds_are_human_readable(self):
        bd = cost.live_breakdown(usage(resp_audio=2500), "gemini-3.1-flash-live-preview")
        assert bd.audio_out_seconds == pytest.approx(100.0)

    def test_llm_calls_add_up(self, settings):
        settings.TEXT_LLM_PRICING = {
            "coach": {"text_in": 1.00, "text_out": 2.00},
            "default": {"text_in": 0, "text_out": 0},
        }
        bd = cost.session_breakdown(
            usage(resp_audio=0),
            "unknown",
            [
                {"model": "coach", "in": 1_000_000, "out": 0},
                {"model": "coach", "in": 0, "out": 1_000_000},
            ],
        )
        assert bd.llm_calls == 2
        assert bd.llm_usd == pytest.approx(3.0)
        assert bd.total_usd == pytest.approx(bd.live_usd + 3.0)

    def test_missing_usage_is_flagged_not_crashed(self):
        bd = cost.live_breakdown(None, "gemini-3.1-flash-live-preview")
        assert bd.total_usd == 0
        assert "usage_missing" in bd.notes

    def test_to_dict_is_json_safe(self):
        bd = cost.session_breakdown(usage(resp_audio=100), "gemini-3.1-flash-live-preview", [])
        data = bd.to_dict()
        assert data["audio_out_tokens"] == 100
        assert isinstance(data["notes"], list)


class TestMergeUsage:
    def test_cumulative_snapshots_do_not_double_count(self):
        """Live kumulyativ yuboradi — maksimum olinadi, qo'shilmaydi."""
        merged = cost.merge_usage(usage(prompt_audio=100), usage(prompt_audio=250))
        assert cost.split_modalities(merged)["audio_in"] == 250

    def test_first_snapshot_passes_through(self):
        first = usage(prompt_audio=10)
        assert cost.merge_usage(None, first) == first
        assert cost.merge_usage({}, first) == first

    def test_empty_incoming_keeps_previous(self):
        prev = usage(prompt_audio=10)
        assert cost.merge_usage(prev, None) == prev

    def test_detail_lists_merge_by_modality(self):
        merged = cost.merge_usage(
            usage(prompt_audio=100, prompt_text=10),
            usage(prompt_audio=300, prompt_text=40),
        )
        parts = cost.split_modalities(merged)
        assert parts["audio_in"] == 300
        assert parts["text_in"] == 40

    def test_snapshot_counter(self):
        merged = cost.merge_usage(usage(prompt_audio=1), usage(prompt_audio=2))
        merged = cost.merge_usage(merged, usage(prompt_audio=3))
        assert merged["snapshots"] == 3


def test_log_line_is_greppable():
    bd = cost.session_breakdown(usage(prompt_audio=2500, resp_audio=1250), "gemini-3.1-flash-live")
    line = cost.log_line("abc-123", bd)
    assert line.startswith("session_cost session_id=abc-123 ")
    assert "audio_in_s=100.0" in line
    assert "audio_out_s=50.0" in line
