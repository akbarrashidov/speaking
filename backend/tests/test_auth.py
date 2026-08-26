"""§4.1 Email + parol autentifikatsiyasi, JWT va kirish himoyasi."""

import time

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.users.jwt_utils import TokenError, decode_token, get_user_from_token, issue_token
from apps.users.models import User

PASSWORD = "TestParol123"


def set_throttle_rates(monkeypatch, **rates):
    """DRF chegaralarini testda o'zgartiradi.

    `settings.REST_FRAMEWORK` ni o'zgartirish yetarli emas: `THROTTLE_RATES`
    klass atributi import paytida bir marta bog'lanadi va qayta o'qilmaydi.
    """
    from django.core.cache import cache
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setattr(
        SimpleRateThrottle,
        "THROTTLE_RATES",
        {"user": "1000/min", "anon": "1000/min", "auth": "1000/min", **rates},
    )
    cache.clear()  # oldingi testlardan qolgan hisoblagichlar


@pytest.fixture(autouse=True)
def relaxed_throttle(monkeypatch):
    """Throttle alohida testda tekshiriladi; qolganlariga xalaqit qilmasin."""
    set_throttle_rates(monkeypatch)


@pytest.fixture
def client():
    return APIClient()


# --- ro'yxatdan o'tish ----------------------------------------------------


@pytest.mark.django_db
def test_register_creates_user_and_returns_jwt(client):
    response = client.post(
        reverse("auth-register"),
        {"email": "Yangi@Example.com", "password": PASSWORD, "first_name": "Aziz"},
        format="json",
    )
    assert response.status_code == 201
    body = response.json()

    assert body["created"] is True
    assert body["user"]["email"] == "yangi@example.com", "email kichik harfga keltirilishi kerak"
    assert body["user"]["first_name"] == "Aziz"
    assert body["expires_in"] > 0
    assert "password" not in str(body)

    user = User.objects.get(email="yangi@example.com")
    assert user.check_password(PASSWORD)
    assert decode_token(body["jwt"])["sub"] == str(user.pk)


@pytest.mark.django_db
def test_register_rejects_duplicate_email_case_insensitively(client):
    User.objects.create_user(email="bor@example.com", password=PASSWORD)
    response = client.post(
        reverse("auth-register"),
        {"email": "BOR@example.com", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.json()["fields"]
    assert User.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("password", ["qisqa", "1234567"])
def test_register_rejects_weak_password(client, password):
    response = client.post(
        reverse("auth-register"),
        {"email": "yangi@example.com", "password": password},
        format="json",
    )
    assert response.status_code == 400
    assert "password" in response.json()["fields"]
    assert not User.objects.exists()


@pytest.mark.django_db
def test_register_rejects_invalid_email(client):
    response = client.post(
        reverse("auth-register"),
        {"email": "email-emas", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.json()["fields"]


# --- kirish ---------------------------------------------------------------


@pytest.mark.django_db
def test_login_returns_jwt(client):
    User.objects.create_user(email="kirish@example.com", password=PASSWORD, first_name="Ali")
    response = client.post(
        reverse("auth-login"),
        {"email": "Kirish@example.com", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert body["user"]["email"] == "kirish@example.com"
    assert get_user_from_token(body["jwt"]).email == "kirish@example.com"


@pytest.mark.django_db
def test_login_rejects_wrong_password(client):
    User.objects.create_user(email="kirish@example.com", password=PASSWORD)
    response = client.post(
        reverse("auth-login"),
        {"email": "kirish@example.com", "password": "BoshqaParol123"},
        format="json",
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_credentials"


@pytest.mark.django_db
def test_login_does_not_reveal_whether_email_exists(client):
    User.objects.create_user(email="bor@example.com", password=PASSWORD)

    known = client.post(
        reverse("auth-login"),
        {"email": "bor@example.com", "password": "NotoQriParol1"},
        format="json",
    )
    unknown = client.post(
        reverse("auth-login"),
        {"email": "yoq@example.com", "password": "NotoQriParol1"},
        format="json",
    )
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()


@pytest.mark.django_db
def test_login_rejects_inactive_user(client):
    User.objects.create_user(email="bloklangan@example.com", password=PASSWORD, is_active=False)
    response = client.post(
        reverse("auth-login"),
        {"email": "bloklangan@example.com", "password": PASSWORD},
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_login_updates_last_active(client):
    user = User.objects.create_user(email="kirish@example.com", password=PASSWORD)
    assert user.last_active_at is None
    client.post(
        reverse("auth-login"),
        {"email": "kirish@example.com", "password": PASSWORD},
        format="json",
    )
    user.refresh_from_db()
    assert user.last_active_at is not None


# --- token --------------------------------------------------------------


@pytest.mark.django_db
def test_refresh_issues_new_token(client, user):
    token, _ = issue_token(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    time.sleep(1)  # `iat` farq qilishi uchun

    response = client.post(reverse("auth-refresh"))
    assert response.status_code == 200
    new_token = response.json()["jwt"]
    assert new_token != token
    assert get_user_from_token(new_token).pk == user.pk


@pytest.mark.django_db
def test_refresh_requires_valid_token(client):
    client.credentials(HTTP_AUTHORIZATION="Bearer buzilgan.token.qiymati")
    assert client.post(reverse("auth-refresh")).status_code == 401


@pytest.mark.django_db
def test_expired_token_is_rejected(user):
    token, _ = issue_token(user, ttl_seconds=-10)
    with pytest.raises(TokenError):
        get_user_from_token(token)


@pytest.mark.django_db
def test_token_of_deleted_user_is_rejected(user):
    token, _ = issue_token(user)
    user.delete()
    with pytest.raises(TokenError):
        get_user_from_token(token)


@pytest.mark.django_db
def test_protected_endpoint_requires_token(client):
    assert client.get(reverse("me")).status_code == 401


# --- throttling -----------------------------------------------------------


@pytest.mark.django_db
def test_login_is_throttled(client, monkeypatch):
    set_throttle_rates(monkeypatch, auth="3/min")
    payload = {"email": "yoq@example.com", "password": "NotoQriParol1"}
    codes = [
        client.post(reverse("auth-login"), payload, format="json").status_code for _ in range(5)
    ]
    assert 429 in codes, f"brute-force chegarasi ishlamadi: {codes}"
