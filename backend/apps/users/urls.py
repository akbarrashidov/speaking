from django.urls import path

from . import views

urlpatterns = [
    path("auth/register", views.register, name="auth-register"),
    path("auth/login", views.login, name="auth-login"),
    path("auth/refresh", views.refresh, name="auth-refresh"),
    path("me", views.me, name="me"),
    path("me/language", views.set_language, name="me-language"),
    path("me/onboarding", views.onboarding, name="me-onboarding"),
    path("config", views.config, name="config"),
]
