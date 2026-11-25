"""Attempts are read-only in the admin site: staff can look, but not add, edit or delete."""

from django.contrib import admin

from .models import Attempt, TestCaseResult


class ReadOnlyAdminMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class TestCaseResultInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = TestCaseResult
    extra = 0
    fields = ("test_case", "status", "exec_time_ms", "error_message")


@admin.register(Attempt)
class AttemptAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("student", "problem", "attempt_no", "is_correct", "tests_passed", "tests_total", "submitted_at")
    list_filter = ("is_correct", "difficulty")
    search_fields = ("student__email", "problem__title")
    inlines = [TestCaseResultInline]
