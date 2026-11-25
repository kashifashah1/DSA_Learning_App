"""Tests for the Step 0 setup: base page, navigation bar, RuleConfig, logging."""

from django.apps import apps
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from users.models import User


class BasePageTests(TestCase):
    def setUp(self):
        # The dashboard needs login (Step 1), so log in a test student first.
        self.user = User.objects.create_user(email="s@example.com", name="Sam", password="Strong#Pass123")
        self.client.force_login(self.user)

    def test_home_page_loads(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome back, Sam")
        self.assertNotContains(response, "Project setup is working")  # the Step 0 placeholder is gone

    def test_navigation_bar_has_all_links(self):
        response = self.client.get(reverse("dashboard"))
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Profile", "Logout"]:
            self.assertContains(response, label)

    def test_page_is_responsive(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'name="viewport"')

    def test_messages_use_one_style(self):
        """A message added in a view shows up in the shared message area."""
        from django.contrib import messages
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        request = RequestFactory().get("/")
        request.session = {}
        request._messages = FallbackStorage(request)
        messages.error(request, "Something went wrong")
        html = render_to_string("partials/messages.html", request=request)
        self.assertIn("Something went wrong", html)
        self.assertIn("bg-red-50", html)


class ProjectSetupTests(TestCase):
    def test_all_six_apps_are_installed(self):
        for name in ["users", "problems", "attempts", "analytics", "recommendations", "web"]:
            self.assertTrue(apps.is_installed(name), name)

    def test_database_is_postgresql(self):
        self.assertIn("postgresql", settings.DATABASES["default"]["ENGINE"])

    def test_csrf_middleware_is_on(self):
        self.assertIn("django.middleware.csrf.CsrfViewMiddleware", settings.MIDDLEWARE)

    def test_log_file_is_configured(self):
        self.assertIn("file", settings.LOGGING["handlers"])
        self.assertTrue(settings.LOG_DIR.exists())


class RuleConfigTests(TestCase):
    """The master prompt's starting values must be present in settings."""

    def test_threshold_values(self):
        self.assertEqual(settings.MIN_ATTEMPTS_PER_TOPIC, 3)
        self.assertEqual(settings.RECENT_WINDOW, 5)
        self.assertEqual(settings.MIN_ATTEMPTS_FOR_MODEL, 100)
        self.assertEqual(settings.REVISION_AFTER_DAYS, 14)
        self.assertEqual(settings.REVISION_ACCURACY_DROP, 0.20)
        self.assertEqual(settings.TARGET_SUCCESS_PROB, 0.6)
        self.assertEqual(settings.CODE_TIME_LIMIT_SEC, 5)

    def test_mastery_weights_add_up_to_one(self):
        self.assertEqual(
            set(settings.MASTERY_WEIGHTS),
            {"accuracy", "recent_accuracy", "speed", "attempt_efficiency"},
        )
        self.assertAlmostEqual(sum(settings.MASTERY_WEIGHTS.values()), 1.0)

    def test_level_ranges(self):
        self.assertEqual(settings.LEVEL_RANGES["BEGINNER_BELOW"], 40)
        self.assertEqual(settings.LEVEL_RANGES["ADVANCED_ABOVE"], 70)
