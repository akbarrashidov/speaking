from django.urls import re_path

from .consumer import SessionConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/session/(?P<session_id>[0-9a-fA-F-]{36})/$",
        SessionConsumer.as_asgi(),
    ),
]
