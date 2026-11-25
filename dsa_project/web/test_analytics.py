"""Tests for the dashboard additions, the analytics page and the chart endpoints (Step 10)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from analytics.services import PerformanceAnalyzer
from attempts.factories import AttemptLog
from attempts.tests import make_student
from problems.models import Problem

ENDPOINTS = ["api_trend", "api_topics", "api_difficulty"]


class AnalyticsTestBase(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student("sam@example.com")
        self.other = make_student("other@example.com")
        self.client.force_login(self.student)
        self.sum = Problem.objects.get(title="Sum of Array")
        self.palindrome = Problem.objects.get(title="Palindrome Check")

    def add_own(self):
        log = AttemptLog(self.student)
        log.many(self.sum, "CCFC")
        log.many(self.palindrome, "FFF")
        PerformanceAnalyzer().sync_student(self.student)

    def add_other(self):
        AttemptLog(self.other).many(self.sum, "CCCCCCC", secs=30)
        PerformanceAnalyzer().sync_student(self.other)


class ChartEndpointTests(AnalyticsTestBase):
    def get_json(self, name):
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        return response.json()

    def test_urls(self):
        self.assertEqual(reverse("api_trend"), "/api/analytics/trend/")
        self.assertEqual(reverse("api_topics"), "/api/analytics/topics/")
        self.assertEqual(reverse("api_difficulty"), "/api/analytics/difficulty/")

    def test_anonymous_users_are_refused_without_any_data(self):
        self.add_own()
        self.client.logout()
        for name in ENDPOINTS:
            with self.subTest(endpoint=name):
                response = self.client.get(reverse(name))
                self.assertIn(response.status_code, (401, 403))
                self.assertNotIn(b"Sum", response.content)

    def test_endpoints_only_read(self):
        for name in ENDPOINTS:
            for method in ("post", "put", "patch", "delete"):
                with self.subTest(endpoint=name, method=method):
                    self.assertEqual(getattr(self.client, method)(reverse(name)).status_code, 405)

    def test_returns_only_the_logged_in_students_data(self):
        self.add_own()
        self.add_other()  # the other student has 7 correct attempts
        trend = self.get_json("api_trend")
        self.assertEqual(sum(point["attempts"] for point in trend), 7)  # sam: 4 + 3, not the other 7 as well
        difficulty = {row["difficulty"]: row for row in self.get_json("api_difficulty")}
        self.assertEqual(sum(row["attempts"] for row in difficulty.values()), 7)
        topics = self.get_json("api_topics")
        self.assertEqual(sum(row["attempts"] for row in topics), 7)

    def test_each_student_sees_a_different_answer(self):
        self.add_own()
        self.add_other()
        mine = self.get_json("api_topics")
        self.client.force_login(self.other)
        theirs = self.get_json("api_topics")
        self.assertNotEqual(mine, theirs)
        self.assertEqual(sum(row["attempts"] for row in theirs), 7)

    def test_a_student_without_attempts_gets_empty_data_not_an_error(self):
        self.assertEqual(self.get_json("api_trend"), [])
        self.assertEqual(self.get_json("api_topics"), [])
        difficulty = self.get_json("api_difficulty")
        self.assertEqual([row["accuracy"] for row in difficulty], [None, None, None])

    def test_the_numbers_are_percentages(self):
        self.add_own()
        topics = {row["topic"]: row for row in self.get_json("api_topics")}
        arrays = topics[self.sum.subtopic.topic.name]
        self.assertEqual(arrays["accuracy"], 75.0)
        strings = topics[self.palindrome.subtopic.topic.name]
        self.assertEqual(strings["accuracy"], 0.0)
        self.assertIn(strings["level"], ["Beginner", "Intermediate", "Advanced"])

    def test_difficulty_has_easy_medium_hard_in_order(self):
        self.add_own()
        self.assertEqual([row["difficulty"] for row in self.get_json("api_difficulty")], ["Easy", "Medium", "Hard"])


class AnalyticsPageTests(AnalyticsTestBase):
    def test_needs_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(reverse("analytics")), f"{reverse('login')}?next=/analytics/")

    def test_a_student_without_attempts_sees_a_message_and_no_charts(self):
        response = self.client.get(reverse("analytics"))
        self.assertContains(response, "No charts yet")
        self.assertNotContains(response, "<canvas")
        self.assertNotContains(response, "chart.umd")

    def test_a_student_with_attempts_sees_the_three_charts_with_help_text(self):
        self.add_own()
        response = self.client.get(reverse("analytics"))
        for chart in ["trend-chart", "topics-chart", "difficulty-chart"]:
            self.assertContains(response, f'id="{chart}"')
        self.assertContains(response, "chart.js")
        self.assertContains(response, reverse("api_trend"))
        self.assertContains(response, "Mastery (0 to 100)")
        self.assertNotContains(response, "No charts yet")

    def test_the_page_contains_none_of_the_data_itself(self):
        self.add_other()
        self.add_own()
        html = self.client.get(reverse("analytics")).content.decode()
        self.assertNotIn("other@example.com", html)
        self.assertNotIn("cumulative_accuracy", html)  # the numbers come only through the endpoints


class DashboardSkillTests(AnalyticsTestBase):
    def test_shows_skill_and_strong_and_weak_topics(self):
        log = AttemptLog(self.student)
        log.many(self.sum, "CCCCC")
        log.many(self.palindrome, "FFFFF")
        PerformanceAnalyzer().sync_student(self.student)
        response = self.client.get(reverse("dashboard"))
        data = response.context["data"]
        self.assertIsNotNone(data.overall_skill)
        self.assertEqual([r.topic for r in data.strong_topics], [self.sum.subtopic.topic])
        self.assertEqual([r.topic for r in data.weak_topics], [self.palindrome.subtopic.topic])
        self.assertContains(response, "Overall skill")
        self.assertContains(response, "Strong topics")
        self.assertContains(response, "Topics to improve")
        self.assertContains(response, "Below 40 is Beginner")  # help text

    def test_not_enough_data_message(self):
        AttemptLog(self.student).many(self.sum, "C")
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Not enough data yet")
        self.assertIsNone(response.context["data"].overall_skill)

    def test_other_students_topics_never_appear(self):
        self.add_other()
        AttemptLog(self.student).many(self.palindrome, "C")
        data = self.client.get(reverse("dashboard")).context["data"]
        self.assertEqual(data.strong_topics, [])
        self.assertEqual(data.weak_topics, [])
