from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def healthz(_request):
    return JsonResponse({"ok": True})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    path("healthz", healthz),
]
