"""Admin pages for the problem catalogue. The admin site is for staff only."""

from django.contrib import admin

from .models import Problem, Subtopic, TestCase, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    search_fields = ("name",)


@admin.register(Subtopic)
class SubtopicAdmin(admin.ModelAdmin):
    list_display = ("name", "topic", "order")
    list_filter = ("topic",)
    search_fields = ("name",)


class TestCaseInline(admin.StackedInline):
    """Test cases are edited inside the Problem page."""

    model = TestCase
    extra = 1
    fields = ("input_data", "expected_output", "is_sample")


@admin.register(Problem)
class ProblemAdmin(admin.ModelAdmin):
    list_display = ("title", "difficulty", "subtopic", "topic_name", "created_at")
    list_filter = ("difficulty", "subtopic__topic", "subtopic")
    search_fields = ("title",)
    inlines = [TestCaseInline]

    @admin.display(description="Topic")
    def topic_name(self, obj):
        return obj.topic.name


@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "problem", "is_sample")
    list_filter = ("is_sample",)
    search_fields = ("problem__title",)
