"""Kunlik pul tomi (§Faza 8).

Sessiya soni cheksiz tarifda kunlik xarajat nazoratsiz o'sishi mumkin edi.
Tom haqiqiy o'lchangan `SessionMetrics.cost_usd` ga tayanadi — taxminga emas.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.practice.models import Session, SessionMetrics, SessionStatus
from apps.users import quota


def spend(user, topic, usd):
    session = Session.objects.create(
        user=user,
        topic=topic,
        mode="anticipation_drill",
        status=SessionStatus.DONE,
        started_at=timezone.now(),
        ended_at=timezone.now(),
    )
    SessionMetrics.objects.create(session=session, cost_usd=Decimal(str(usd)))
    return session


@pytest.mark.django_db
class TestSpentToday:
    def test_no_sessions_means_zero(self, user):
        assert quota.spent_today(user) == Decimal("0")

    def test_sums_todays_sessions(self, user, topic):
        spend(user, topic, "0.031")
        spend(user, topic, "0.019")
        assert quota.spent_today(user) == Decimal("0.050000")

    def test_other_users_spending_is_not_counted(self, user, premium_user, topic):
        spend(premium_user, topic, "5.00")
        assert quota.spent_today(user) == Decimal("0")


@pytest.mark.django_db
class TestCap:
    def test_cap_off_by_default(self, premium_user, topic, settings):
        settings.DAILY_COST_CAP_USD = 0
        spend(premium_user, topic, "99.00")
        assert quota.consume(premium_user).plan == "premium"

    def test_under_the_cap_is_allowed(self, premium_user, topic, settings):
        settings.DAILY_COST_CAP_USD = 0.10
        spend(premium_user, topic, "0.04")
        assert quota.consume(premium_user).used == 1

    def test_reaching_the_cap_blocks_a_new_session(self, premium_user, topic, settings):
        """Cheksiz sessiyali tarifda ham pul tomi ishlaydi."""
        settings.DAILY_COST_CAP_USD = 0.10
        spend(premium_user, topic, "0.12")

        with pytest.raises(quota.QuotaExceeded) as exc:
            quota.consume(premium_user)
        assert exc.value.reason == "cost_cap_reached"
        assert exc.value.next_available_at is not None

    def test_cap_reports_a_distinct_reason_from_the_session_limit(self, user, topic, settings):
        """Ikki turli sabab — foydalanuvchiga turli xabar ko'rsatiladi."""
        settings.DAILY_COST_CAP_USD = 0
        settings.SESSION_LIMITS = {
            **settings.SESSION_LIMITS,
            "free": {"daily_sessions": 1, "duration_seconds": 300},
        }
        quota.consume(user)
        with pytest.raises(quota.QuotaExceeded) as exc:
            quota.consume(user)
        assert exc.value.reason == "quota_exceeded"


@pytest.mark.django_db
def test_start_session_surfaces_the_cap_as_402(auth_client, premium_user, topic, settings):
    from rest_framework.test import APIClient

    from apps.users.jwt_utils import issue_token

    settings.DAILY_COST_CAP_USD = 0.05
    spend(premium_user, topic, "0.09")

    client = APIClient()
    token, _ = issue_token(premium_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = client.post("/api/sessions/start", {"topic_id": topic.id}, format="json")
    assert response.status_code == 402
    assert response.json()["error"] == "cost_cap_reached"
