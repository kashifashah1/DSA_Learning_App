from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Simple admin page for users (staff only). Passwords are not shown here."""

    list_display = ("email", "name", "is_staff", "is_active", "date_joined")
    search_fields = ("email", "name")
    list_filter = ("is_staff", "is_active")
    readonly_fields = ("password", "last_login", "date_joined")
    fields = ("name", "email", "is_staff", "is_active", "password", "last_login", "date_joined")
