"""Tests for the real dashboard (it only shows the student's own real data)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from attempts.factories import AttemptLog
from attempts.tests import make_attempt, make_student
from problems.models import Problem
from recommendations.models import Recommendation


class DashboardTestBase(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student("sam@example.com")
        self.client.force_login(self.student)
        self.url = reverse("dashboard")
        self.sum = Problem.objects.get(title="Sum of Array")
        self.palindrome = Problem.objects.get(title="Palindrome Check")
        self.vowels = Problem.objects.get(title="Count Vowels")


class DashboardBasicsTests(DashboardTestBase):
    def test_the_dashboard_url(self):
        self.assertEqual(self.url, "/dashboard/")

    def test_needs_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('login')}?next={self.url}")

    def test_greets_the_student_by_name_and_has_no_placeholder(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Welcome back, Sam")
        self.assertNotContains(response, "Project setup is working")

    def test_has_the_navigation_bar(self):
        response = self.client.get(self.url)
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Profile", "Logout"]:
            self.assertContains(response, label)


class NewStudentTests(DashboardTestBase):
    def test_shows_a_clear_way_to_start_and_no_numbers(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Let's solve your first problem")
        self.assertContains(response, f'href="{reverse("problems")}"')
        self.assertContains(response, f'href="{reverse("roadmap")}"')
        for invented in ["Problems solved", "Problems tried", "Submissions", "Recent attempts"]:
            self.assertNotContains(response, invented)
        self.assertNotContains(response, "Recommended next")

    def test_nothing_is_invented_when_the_data_is_empty(self):
        data = self.client.get(self.url).context["data"]
        self.assertEqual((data.solved_count, data.tried_count, data.attempts_count), (0, 0, 0))
        self.assertFalse(data.has_attempts)
        self.assertEqual(data.recent_attempts, [])
        self.assertIsNone(data.recommendation)


class ProgressNumbersTests(DashboardTestBase):
    def test_counts_come_from_the_students_own_attempts(self):
        make_attempt(self.student, self.sum, attempt_no=1, is_correct=False)
        make_attempt(self.student, self.sum, attempt_no=2, is_correct=True)
        make_attempt(self.student, self.sum, attempt_no=3, is_correct=True)  # solved twice: still one problem
        make_attempt(self.student, self.palindrome, attempt_no=1, is_correct=False)  # tried, not solved
        make_attempt(self.student, self.vowels, attempt_no=1, is_correct=True)
        data = self.client.get(self.url).context["data"]
        self.assertEqual(data.solved_count, 2)  # Sum of Array, Count Vowels
        self.assertEqual(data.tried_count, 3)
        self.assertEqual(data.attempts_count, 5)
        self.assertEqual(data.total_problems, 12)

    def test_the_numbers_are_on_the_page(self):
        make_attempt(self.student, self.sum, attempt_no=1, is_correct=True)
        response = self.client.get(self.url)
        self.assertContains(response, "Problems solved")
        self.assertContains(response, "of 12")
        self.assertNotContains(response, "Let's solve your first problem")

    def test_another_students_attempts_are_not_counted_or_shown(self):
        other = make_student("other@example.com")
        make_attempt(other, self.palindrome, attempt_no=1, is_correct=True)
        make_attempt(other, self.vowels, attempt_no=1, is_correct=True)
        Recommendation.objects.create(student=other, activity="HARDER", problem=self.vowels, reason="OTHER-STUDENTS-REASON")
        response = self.client.get(self.url)
        self.assertEqual(response.context["data"].attempts_count, 0)
        self.assertNotContains(response, "OTHER-STUDENTS-REASON")
        self.assertNotContains(response, "Palindrome Check")


class RecentAttemptsTests(DashboardTestBase):
    def test_shows_the_five_newest_attempts_newest_first(self):
        log = AttemptLog(self.student)
        problems = [self.sum, self.palindrome, self.vowels] + list(Problem.objects.exclude(
            pk__in=[self.sum.pk, self.palindrome.pk, self.vowels.pk])[:4])
        attempts = [log.add(problem, True) for problem in problems]  # 7 attempts, oldest first
        shown = self.client.get(self.url).context["data"].recent_attempts
        self.assertEqual([a.pk for a in shown], [a.pk for a in reversed(attempts[-5:])])

    def test_each_row_shows_the_result_and_links(self):
        make_attempt(self.student, self.sum, attempt_no=1, is_correct=True, tests_passed=5, tests_total=5)
        make_attempt(self.student, self.palindrome, attempt_no=1, is_correct=False, tests_passed=2, tests_total=5)
        response = self.client.get(self.url)
        for text in ["Sum of Array", "Palindrome Check", "Passed", "Failed", "5 of 5", "2 of 5"]:
            self.assertContains(response, text)
        self.assertContains(response, f'href="{reverse("problem_detail", args=[self.sum.pk])}"')
        self.assertContains(response, f'href="{reverse("attempt_history", args=[self.sum.pk])}"')


class RecommendationOnDashboardTests(DashboardTestBase):
    def test_shows_the_newest_recommendation_with_reason_and_button(self):
        make_attempt(self.student, self.sum, attempt_no=1, is_correct=True)
        Recommendation.objects.create(student=self.student, activity="SAME", problem=self.palindrome, reason="OLD one")
        Recommendation.objects.create(student=self.student, activity="HARDER", problem=self.vowels, reason="NEWEST reason text")
        response = self.client.get(self.url)
        self.assertContains(response, "Recommended next")
        self.assertContains(response, "NEWEST reason text")
        self.assertNotContains(response, "OLD one")
        self.assertContains(response, "Open this problem")
        self.assertContains(response, f'href="{reverse("problem_detail", args=[self.vowels.pk])}"')

    def test_attempts_but_no_recommendation_says_so_calmly(self):
        make_attempt(self.student, self.sum, attempt_no=1, is_correct=True)
        response = self.client.get(self.url)
        self.assertContains(response, "You will get a recommendation after your next submission")
        self.assertNotContains(response, "Recommended next")

    def test_a_real_submission_leads_to_a_recommendation_on_the_dashboard(self):
        """The whole chain: submit -> evaluator -> attempt -> engine -> dashboard."""
        url = reverse("problem_detail", args=[self.sum.pk])
        self.client.post(url, {"source_code": "input()\nprint(sum(map(int, input().split())))"})
        response = self.client.get(self.url)
        self.assertContains(response, "Recommended next")
        self.assertContains(response, "Sum of Array")
        self.assertContains(response, "5 of 5")
        self.assertEqual(response.context["data"].solved_count, 1)
