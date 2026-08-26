from django.urls import path

from . import views

urlpatterns = [
    path("sessions", views.sessions_list, name="sessions-list"),
    path("sessions/start", views.sessions_start, name="sessions-start"),
    path("placement/start", views.placement_start, name="placement-start"),
    path("sessions/<uuid:session_id>/end", views.sessions_end, name="sessions-end"),
    path(
        "sessions/<uuid:session_id>/feedback",
        views.sessions_feedback,
        name="sessions-feedback",
    ),
]
