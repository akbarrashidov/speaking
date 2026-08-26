from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("api/", include("apps.users.urls")),
    path("api/", include("apps.content.urls")),
    path("api/", include("apps.practice.urls")),
    path("api/", include("apps.progress.urls")),
]
