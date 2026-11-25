"""Tests for security, reliability and the error pages (Step 11)."""

import re
import subprocess
import sys
import tokenize
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from attempts.tests import make_student
from users.models import User

BASE = Path(settings.BASE_DIR)
PROJECT_PYTHON_FILES = [
    p for p in BASE.rglob("*.py")
    if not any(part in {"migrations", ".venv", "venv", "__pycache__"} for part in p.parts)
    and not p.name.startswith("test")
]


class AccessControlTests(TestCase):
    def setUp(self):
        self.student = make_student("sam@example.com")

    def test_every_page_but_login_register_landing_and_password_reset_needs_login(self):
        for url in ["/dashboard/", "/roadmap/", "/problems/", "/analytics/", "/profile/", "/problems/1/",
                    "/problems/1/attempts/"]:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_admin_is_staff_only(self):
        self.assertEqual(self.client.get("/admin/").status_code, 302)  # anonymous: to the admin login
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/admin/").status_code, 302)  # a student is not staff
        staff = User.objects.create_user(email="boss@example.com", name="Boss", password="Strong#Pass123", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_the_login_page_offers_forgot_password(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Forgot your password?")
        self.assertContains(response, reverse("password_reset"))

    def test_posts_without_a_csrf_token_are_refused(self):
        self.student.set_password("Strong#Pass123")
        self.student.save()
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        self.assertEqual(strict.post("/profile/", {"name": "X", "email": "x@example.com"}).status_code, 403)
        self.assertEqual(strict.post("/logout/").status_code, 403)

    def test_post_forms_carry_a_csrf_token(self):
        for path in (BASE / "templates").rglob("*.html"):
            html = path.read_text(encoding="utf-8")
            for form in re.findall(r"<form\b[^>]*>.*?</form>", html, flags=re.S):
                if re.search(r'method="post"', form, flags=re.I):
                    with self.subTest(template=path.name):
                        self.assertIn("csrf_token", form)


class CodeReviewTests(TestCase):
    def test_no_raw_sql_in_the_project(self):
        pattern = re.compile(r"\.raw\(|\.extra\(|connection\.cursor|cursor\(\)|RawSQL")
        for path in PROJECT_PYTHON_FILES:
            with self.subTest(file=path.name):
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")))

    def test_no_threshold_numbers_hidden_in_the_logic(self):
        """Numbers written in the code of the logic files may only be small structural ones
        (0, 1, rounding digits, 100 for percent, 1000 for milliseconds). Every threshold and
        weight (0.6, 0.20, 14, 100 attempts, ...) must come from settings.py."""
        allowed = {0, 1, 2, 3, 4, 6, 9, 100, 1000}
        for path in [BASE / "analytics" / "services.py", BASE / "analytics" / "ml.py",
                     BASE / "recommendations" / "engine.py"]:
            with open(path, "rb") as handle:
                numbers = [t.string for t in tokenize.tokenize(handle.readline) if t.type == tokenize.NUMBER]
            with self.subTest(file=path.name):
                unexpected = [n for n in numbers if float(n) not in allowed]
                self.assertEqual(unexpected, [])

    def test_views_have_no_scoring_logic(self):
        for name in ["views.py", "api.py"]:
            text = (BASE / "web" / name).read_text(encoding="utf-8")
            for word in ["mastery_score", "recent_accuracy", "RecommendationEngine", "predict_probability"]:
                with self.subTest(file=name, word=word):
                    self.assertNotIn(word, text)

    def test_only_needed_personal_data_is_stored(self):
        fields = {f.name for f in User._meta.get_fields() if getattr(f, "concrete", False)}
        self.assertEqual(fields, {"id", "password", "last_login", "name", "email", "is_staff", "is_active", "date_joined"})

    def test_out_of_scope_apps_are_not_installed(self):
        for forbidden in ["channels", "celery", "allauth", "social_django"]:
            self.assertNotIn(forbidden, settings.INSTALLED_APPS)


class HttpsSettingsTests(TestCase):
    """HTTPS settings are switched on only through the HTTPS_ENABLED environment variable."""

    def read_settings(self, **env):
        code = (
            "import os, sys; sys.path.insert(0, r'%s'); os.environ['DJANGO_SETTINGS_MODULE']='dsa_learning.settings';"
            "from django.conf import settings as s;"
            "print(s.HTTPS_ENABLED, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS)"
        ) % BASE
        import os
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, **env})
        return result.stdout.strip()

    def test_off_by_default(self):
        self.assertEqual(self.read_settings(HTTPS_ENABLED="False"), "False False False False 0")

    def test_on_when_the_variable_is_set(self):
        self.assertEqual(self.read_settings(HTTPS_ENABLED="True"), "True True True True 3600")

    def test_placeholder_secret_key_is_refused_without_debug(self):
        result = subprocess.run(
            [sys.executable, "-c", f"import os, sys; sys.path.insert(0, r'{BASE}');"
             "os.environ['DJANGO_SETTINGS_MODULE']='dsa_learning.settings';"
             "from django.conf import settings; settings.DEBUG"],
            capture_output=True, text=True,
            env={**__import__('os').environ, "DEBUG": "False", "SECRET_KEY": "change-me-in-your-env-file"},
        )
        self.assertIn("SECRET_KEY", result.stderr)


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
class ErrorPageTests(TestCase):
    def setUp(self):
        self.student = make_student("sam@example.com")

    def test_404_for_a_logged_in_student_keeps_the_navigation_bar(self):
        self.client.force_login(self.student)
        response = self.client.get("/no/such/page/")
        self.assertContains(response, "This page does not exist", status_code=404)
        self.assertContains(response, ">Dashboard</a>", status_code=404)
        self.assertContains(response, ">Analytics</a>", status_code=404)

    def test_404_for_a_visitor_has_no_student_navigation(self):
        response = self.client.get("/no/such/page/")
        self.assertContains(response, "This page does not exist", status_code=404)
        self.assertNotContains(response, ">Roadmap</a>", status_code=404)
        self.assertContains(response, "Log in", status_code=404)

    def test_missing_problem_gives_the_styled_404(self):
        self.client.force_login(self.student)
        self.assertContains(self.client.get("/problems/999999/"), "This page does not exist", status_code=404)

    def test_500_page_is_styled_and_the_error_is_logged(self):
        self.client.force_login(self.student)
        self.client.raise_request_exception = False
        with mock.patch("web.services.RoadmapService.get_roadmap", side_effect=RuntimeError("boom")):
            with self.assertLogs("django.request", level="ERROR") as logs:
                response = self.client.get("/roadmap/")
        self.assertContains(response, "Something went wrong on our side", status_code=500)
        self.assertNotContains(response, "boom", status_code=500)  # no internal detail shown
        self.assertTrue(any("boom" in line for line in logs.output))

    def test_403_page_is_styled(self):
        strict = Client(enforce_csrf_checks=True)
        response = strict.post(reverse("login"), {"username": "a", "password": "b"})
        self.assertEqual(response.status_code, 403)


class ReliabilityTests(TestCase):
    def test_a_missing_model_file_does_not_break_a_page(self):
        student = make_student("sam@example.com")
        self.client.force_login(student)
        self.assertFalse(settings.MODEL_PATH.exists())
        for url in ["/dashboard/", "/roadmap/", "/problems/", "/analytics/"]:
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_failure_after_saving_does_not_lose_the_attempt(self):
        from attempts.models import Attempt
        from attempts.tests import make_problem
        from web.submission import SubmissionService
        from web.test_submission_service import FakeEvaluator, add_cases, clock

        student, problem = make_student("a@example.com"), make_problem()
        add_cases(problem)
        service = SubmissionService(evaluator=FakeEvaluator(), clock=clock)
        with mock.patch("analytics.services.PerformanceAnalyzer.update_topic_performance", side_effect=RuntimeError("x")):
            with self.assertLogs("web.submission", level="ERROR"):
                service.submit(student, problem, "print(1)")
        self.assertEqual(Attempt.objects.count(), 1)

    def test_the_log_file_setting_exists(self):
        handler = settings.LOGGING["handlers"]["file"]
        self.assertTrue(str(handler["filename"]).endswith("app.log"))
