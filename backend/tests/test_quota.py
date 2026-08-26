"""§4.9 kvota logikasi — kalendar kun Asia/Tashkent bo'yicha."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.users import quota
from apps.users.models import DailyQuota

UTC = ZoneInfo("UTC")
TASHKENT = ZoneInfo("Asia/Tashkent")


def test_free_user_gets_one_session_per_day(user):
    status = quota.get_status(user)
    assert status.limit == 1
    assert status.remaining == 1
    assert status.duration_seconds == 300

    quota.consume(user)
    status = quota.get_status(user)
    assert status.remaining == 0
    assert status.next_available_at is not None


def test_second_session_same_day_is_rejected(user):
    quota.consume(user)
    with pytest.raises(quota.QuotaExceeded) as exc:
        quota.consume(user)
    assert exc.value.next_available_at is not None


def test_premium_user_is_unlimited_with_longer_sessions(premium_user):
    status = quota.get_status(premium_user)
    assert status.limit is None
    assert status.remaining is None
    assert status.duration_seconds == 900

    for _ in range(5):
        quota.consume(premium_user)

    status = quota.get_status(premium_user)
    assert status.used == 5
    assert status.next_available_at is None


def test_quota_day_boundary_uses_tashkent_timezone(user):
    """22:00 UTC — Toshkentda allaqachon ertangi kun (UTC+5)."""
    late_utc = datetime(2026, 3, 10, 22, 0, tzinfo=UTC)
    early_utc = datetime(2026, 3, 10, 18, 0, tzinfo=UTC)

    assert quota.local_today(early_utc) == datetime(2026, 3, 10).date()
    assert quota.local_today(late_utc) == datetime(2026, 3, 11).date()

    quota.consume(user, now=early_utc)
    # Yangi Toshkent kuni — limit tiklanadi.
    status = quota.consume(user, now=late_utc)
    assert status.used == 1


def test_refund_returns_the_session(user):
    quota.consume(user)
    assert quota.get_status(user).remaining == 0

    quota.refund(user)
    assert quota.get_status(user).remaining == 1


def test_refund_never_goes_negative(user):
    quota.refund(user)
    quota.refund(user)
    row = DailyQuota.objects.filter(user=user).first()
    assert row is None or row.sessions_used >= 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("none", None), ("NONE", None), ("unlimited", None), ("", None), ("3", 3), ("xato", 1)],
)
def test_daily_limit_can_be_disabled_from_env(monkeypatch, raw, expected):
    """`FREE_DAILY_SESSIONS=none` → cheksiz (sinov rejimi uchun)."""
    from config.settings import env_int_or_none

    monkeypatch.setenv("FREE_DAILY_SESSIONS", raw)
    assert env_int_or_none("FREE_DAILY_SESSIONS", 1) == expected


def test_unlimited_free_plan_never_raises(user, settings):
    settings.SESSION_LIMITS = {
        **settings.SESSION_LIMITS,
        "free": {"daily_sessions": None, "duration_seconds": 120},
    }
    for _ in range(3):
        quota.consume(user)

    status = quota.get_status(user)
    assert (status.limit, status.remaining, status.used) == (None, None, 3)
    assert status.duration_seconds == 120
    assert status.next_available_at is None


def test_next_reset_is_local_midnight(user):
    now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    reset = quota.next_reset_at(now)
    local = reset.astimezone(TASHKENT)
    assert (local.hour, local.minute) == (0, 0)
    assert local.date() == datetime(2026, 3, 11).date()
