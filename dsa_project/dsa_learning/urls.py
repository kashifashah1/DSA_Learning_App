"""Project URL configuration. Each app keeps its own urls.py (added step by step)."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),  # admin functions are staff-only
    path("", include("users.urls")),  # register, login, logout, profile
    path("", include("web.urls")),
]
