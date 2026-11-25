"""Tests for the attempt history page of one problem (own attempts only)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from attempts.models import Attempt
from attempts.tests import make_attempt, make_student
from problems.models import Problem


class AttemptHistoryPageTests(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.problem = Problem.objects.get(title="Sum of Array")
        self.other_problem = Problem.objects.get(title="Palindrome Check")
        self.sam = make_student("sam@example.com")
        self.priya = make_student("priya@example.com")
        self.client.force_login(self.sam)
        self.url = reverse("attempt_history", args=[self.problem.pk])

    def test_url_looks_like_the_ui_plan(self):
        self.assertEqual(self.url, f"/problems/{self.problem.pk}/attempts/")

    def test_page_needs_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('login')}?next={self.url}")

    def test_unknown_problem_gives_404(self):
        response = self.client.get(reverse("attempt_history", args=[999999]))
        self.assertEqual(response.status_code, 404)

    def test_shows_the_students_own_attempts_newest_first(self):
        make_attempt(self.sam, self.problem, attempt_no=1, is_correct=False, tests_passed=2, tests_total=5)
        make_attempt(self.sam, self.problem, attempt_no=2, is_correct=True, tests_passed=5, tests_total=5)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([a.attempt_no for a in response.context["attempts"]], [2, 1])
        self.assertContains(response, "2 attempts")
        self.assertContains(response, "2 of 5")
        self.assertContains(response, "5 of 5")

    def test_shows_result_time_and_execution_details(self):
        make_attempt(self.sam, self.problem, attempt_no=1, is_correct=True, time_taken_sec=200, exec_time_ms=130)
        make_attempt(self.sam, self.problem, attempt_no=2, is_correct=False, time_taken_sec=45, exec_time_ms=None)
        response = self.client.get(self.url)
        for text in ["#1", "#2", "Passed", "Failed", "3 min 20 s", "45 s", "130 ms", "Not available"]:
            self.assertContains(response, text)

    def test_shows_problem_details_and_breadcrumb(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Sum of Array")
        self.assertContains(response, "Easy")
        self.assertContains(response, "Arrays / Traversal and Counting")
        self.assertContains(response, 'aria-label="Breadcrumb"')
        self.assertContains(response, f'href="{reverse("problems")}"')

    def test_navigation_bar_is_shown(self):
        response = self.client.get(self.url)
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Profile", "Logout"]:
            self.assertContains(response, label)

    # --- the privacy rule ---------------------------------------------------
    def test_another_students_attempts_are_never_visible(self):
        make_attempt(self.sam, self.problem, attempt_no=1, tests_passed=1, tests_total=5)
        # Priya's attempts use values that Sam's page could never show by accident.
        make_attempt(
            self.priya, self.problem, attempt_no=1, is_correct=True, tests_passed=4, tests_total=9,
            time_taken_sec=777, exec_time_ms=4242,
        )
        make_attempt(self.priya, self.problem, attempt_no=2, is_correct=True, tests_passed=8, tests_total=9)
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["attempts"]), 1)
        for secret in ["4 of 9", "8 of 9", "12 min 57 s", "4242 ms", "2 attempts"]:
            self.assertNotContains(response, secret)

    def test_each_student_sees_only_their_own_for_the_same_problem(self):
        make_attempt(self.sam, self.problem, attempt_no=1, tests_passed=1, tests_total=5)
        make_attempt(self.priya, self.problem, attempt_no=1, tests_passed=4, tests_total=9)
        sam_page = self.client.get(self.url)
        self.client.force_login(self.priya)
        priya_page = self.client.get(self.url)
        self.assertContains(sam_page, "1 of 5")
        self.assertNotContains(sam_page, "4 of 9")
        self.assertContains(priya_page, "4 of 9")
        self.assertNotContains(priya_page, "1 of 5")

    def test_student_with_no_attempts_sees_empty_state_even_if_others_have_some(self):
        make_attempt(self.priya, self.problem, attempt_no=1, is_correct=True)
        response = self.client.get(self.url)
        self.assertContains(response, "You have not attempted this problem yet.")
        self.assertEqual(len(response.context["attempts"]), 0)
        self.assertContains(response, f'href="{reverse("problems")}"')

    def test_attempts_of_other_problems_are_not_mixed_in(self):
        make_attempt(self.sam, self.other_problem, attempt_no=1, tests_passed=3, tests_total=7)
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["attempts"]), 0)
        self.assertNotContains(response, "3 of 7")

    def test_page_cannot_be_used_to_change_attempts(self):
        attempt = make_attempt(self.sam, self.problem, attempt_no=1, is_correct=False)
        response = self.client.post(self.url, {"is_correct": "on", "tests_passed": 5})
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Attempt.objects.get(pk=attempt.pk).is_correct)
        self.assertEqual(Attempt.objects.count(), 1)


class HistoryLinkInProblemListTests(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student()
        self.client.force_login(self.student)
        self.tried = Problem.objects.get(title="Sum of Array")
        self.untouched = Problem.objects.get(title="Palindrome Check")
        make_attempt(self.student, self.tried, is_correct=False)

    def test_history_link_only_for_problems_the_student_has_tried(self):
        response = self.client.get(reverse("problems"))
        self.assertContains(response, f'href="{reverse("attempt_history", args=[self.tried.pk])}"')
        self.assertNotContains(response, f'href="{reverse("attempt_history", args=[self.untouched.pk])}"')
