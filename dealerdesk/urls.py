from django.contrib import admin
from django.urls import include, path

from core.views_ui import dashboard_view

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
]
