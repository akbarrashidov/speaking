import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# HTTP ilovasi apps import qilinishidan oldin yuklanadi (Channels talabi).
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.practice.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Auth WS consumer ichida JWT orqali bajariladi (§4.1), shuning uchun
        # AuthMiddlewareStack shart emas.
        "websocket": URLRouter(websocket_urlpatterns),
    }
)
