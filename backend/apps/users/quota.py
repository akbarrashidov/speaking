"""Kvota logikasi (§4.9). Server tomonida, sessiya boshlanishidan oldin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import DailyQuota, User


class QuotaExceeded(Exception):
    def __init__(self, next_available_at, reason: str = "quota_exceeded"):
        self.next_available_at = next_available_at
        self.reason = reason
        super().__init__(reason)


@dataclass
class QuotaStatus:
    plan: str
    limit: int | None  # None → cheksiz
    used: int
    remaining: int | None
    duration_seconds: int
    next_available_at: datetime | None


def quota_tz() -> ZoneInfo:
    return ZoneInfo(settings.QUOTA_TIMEZONE)


def local_today(now: datetime | None = None) -> date:
    now = now or timezone.now()
    return now.astimezone(quota_tz()).date()


def next_reset_at(now: datetime | None = None) -> datetime:
    """Keyingi kalendar kun boshlanishi (UTC'da qaytariladi)."""
    tz = quota_tz()
    now = (now or timezone.now()).astimezone(tz)
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, dtime.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))


def limits_for(user: User) -> dict:
    cfg = settings.SESSION_LIMITS[user.plan]
    if settings.DEV_UNLOCK_ALL:
        # Sinov rejimi: sessiya soni cheksiz, davomiylik premium darajasida.
        return {
            "daily_sessions": None,
            "duration_seconds": settings.SESSION_LIMITS["premium"]["duration_seconds"],
        }
    return cfg


def get_status(user: User, now: datetime | None = None) -> QuotaStatus:
    cfg = limits_for(user)
    limit = cfg["daily_sessions"]
    used = (
        DailyQuota.objects.filter(user=user, date=local_today(now))
        .values_list("sessions_used", flat=True)
        .first()
        or 0
    )
    if limit is None:
        remaining = None
        exhausted = False
    else:
        remaining = max(0, limit - used)
        exhausted = remaining == 0
    return QuotaStatus(
        plan=user.plan,
        limit=limit,
        used=used,
        remaining=remaining,
        duration_seconds=cfg["duration_seconds"],
        next_available_at=next_reset_at(now) if exhausted else None,
    )


@transaction.atomic
def consume(user: User, now: datetime | None = None) -> QuotaStatus:
    """Bitta sessiyani hisobdan chiqaradi. Limit tugagan bo'lsa QuotaExceeded."""
    cfg = limits_for(user)
    limit = cfg["daily_sessions"]
    today = local_today(now)

    row, _ = DailyQuota.objects.select_for_update().get_or_create(
        user=user, date=today, defaults={"sessions_used": 0}
    )
    if limit is not None and row.sessions_used >= limit:
        raise QuotaExceeded(next_reset_at(now))

    # Ikkinchi tom — pul bo'yicha (§Faza 8). Sessiya soni cheksiz bo'lgan
    # tarifda ham kunlik sarf nazoratsiz o'sib ketmasligi kerak.
    if not settings.DEV_UNLOCK_ALL and spent_today(user, now) >= settings.DAILY_COST_CAP_USD > 0:
        raise QuotaExceeded(next_reset_at(now), "cost_cap_reached")

    DailyQuota.objects.filter(pk=row.pk).update(sessions_used=F("sessions_used") + 1)
    row.refresh_from_db(fields=["sessions_used"])

    remaining = None if limit is None else max(0, limit - row.sessions_used)
    return QuotaStatus(
        plan=user.plan,
        limit=limit,
        used=row.sessions_used,
        remaining=remaining,
        duration_seconds=cfg["duration_seconds"],
        next_available_at=next_reset_at(now) if remaining == 0 else None,
    )


def spent_today(user: User, now: datetime | None = None) -> Decimal:
    """Bugun shu foydalanuvchiga ketgan haqiqiy pul (Live + LLM chaqiruvlari).

    Manba — `SessionMetrics.cost_usd`, ya'ni taxmin emas, o'lchangan qiymat
    (`apps/practice/cost.py`).
    """
    from apps.practice.models import SessionMetrics

    tz = quota_tz()
    start = datetime.combine(local_today(now), dtime.min, tzinfo=tz)
    total = SessionMetrics.objects.filter(
        session__user=user, session__created_at__gte=start
    ).aggregate(total=Sum("cost_usd"))["total"]
    return total or Decimal("0")


@transaction.atomic
def refund(user: User, now: datetime | None = None) -> None:
    """Sessiya boshlanmay qolsa kvotani qaytaradi (masalan WS ulanmadi)."""
    today = local_today(now)
    row = DailyQuota.objects.select_for_update().filter(user=user, date=today).first()
    if row and row.sessions_used > 0:
        DailyQuota.objects.filter(pk=row.pk).update(sessions_used=F("sessions_used") - 1)
