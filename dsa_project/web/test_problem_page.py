"""Tests for the problem page and the submission flow in the browser (Step 6)."""

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from attempts.models import Attempt
from attempts.tests import make_attempt, make_problem, make_student
from problems.models import Problem
from problems.models import TestCase as ProblemTestCase
from problems.models import Topic
from recommendations.engine import RecommendationEngine
from recommendations.models import Recommendation

SUM_CODE = "input()\nprint(sum(map(int, input().split())))\n"
WRONG_CODE = "input()\nprint(sum(map(int, input().split())) + 1)\n"


class ProblemPageTestBase(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student()
        self.client.force_login(self.student)
        self.problem = Problem.objects.get(title="Sum of Array")  # 5 test cases, the first 2 are samples
        self.url = reverse("problem_detail", args=[self.problem.pk])
        self.session_key = f"problem_opened_{self.problem.pk}"

    def submit(self, code=SUM_CODE, **extra):
        return self.client.post(self.url, {"source_code": code}, **extra)


class ProblemPageContentTests(ProblemPageTestBase):
    def test_url_looks_like_the_ui_plan(self):
        self.assertEqual(self.url, f"/problems/{self.problem.pk}/")

    def test_page_needs_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('login')}?next={self.url}")

    def test_unknown_problem_gives_404(self):
        self.assertEqual(self.client.get(reverse("problem_detail", args=[999999])).status_code, 404)

    def test_shows_title_difficulty_topic_and_statement(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sum of Array")
        self.assertContains(response, "Easy")
        self.assertContains(response, "Arrays / Traversal and Counting")
        self.assertContains(response, "print the sum of all its elements")
        self.assertContains(response, 'aria-label="Breadcrumb"')

    def test_shows_only_the_sample_test_cases(self):
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["samples"]), 2)
        self.assertContains(response, "Sample 1")
        self.assertContains(response, "Sample 2")
        self.assertNotContains(response, "Sample 3")

    def test_hidden_test_cases_are_never_in_the_page(self):
        problem = make_problem("Secret tests")
        ProblemTestCase.objects.create(problem=problem, input_data="SAMPLE-IN", expected_output="SAMPLE-OUT", is_sample=True)
        ProblemTestCase.objects.create(problem=problem, input_data="HIDDEN-IN-9", expected_output="HIDDEN-OUT-9")
        response = self.client.get(reverse("problem_detail", args=[problem.pk]))
        self.assertContains(response, "SAMPLE-IN")
        self.assertContains(response, "SAMPLE-OUT")
        self.assertNotContains(response, "HIDDEN-IN-9")
        self.assertNotContains(response, "HIDDEN-OUT-9")

    def test_has_code_area_submit_button_and_csrf_token(self):
        response = self.client.get(self.url)
        self.assertContains(response, '<textarea id="source_code" name="source_code"')
        self.assertContains(response, ">Submit</button>")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "Python 3")

    def test_shows_time_limit_navigation_and_history_link(self):
        response = self.client.get(self.url)
        self.assertContains(response, "time limit of 5 seconds")
        self.assertContains(response, reverse("attempt_history", args=[self.problem.pk]))
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Profile", "Logout"]:
            self.assertContains(response, label)

    def test_only_get_and_post_are_allowed(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)

    def test_problem_list_and_history_page_link_to_the_problem(self):
        self.assertContains(self.client.get(reverse("problems")), f'href="{self.url}"')
        history = self.client.get(reverse("attempt_history", args=[self.problem.pk]))
        self.assertContains(history, f'href="{self.url}"')


class OpeningTimeTests(ProblemPageTestBase):
    def test_opening_the_page_stores_the_time_in_the_session(self):
        self.assertNotIn(self.session_key, self.client.session)
        self.client.get(self.url)
        self.assertIn(self.session_key, self.client.session)

    def test_each_problem_has_its_own_key(self):
        other = Problem.objects.get(title="Palindrome Check")
        self.client.get(self.url)
        self.client.get(reverse("problem_detail", args=[other.pk]))
        self.assertIn(self.session_key, self.client.session)
        self.assertIn(f"problem_opened_{other.pk}", self.client.session)

    def test_reloading_keeps_the_first_opening_time(self):
        self.client.get(self.url)
        first = self.client.session[self.session_key]
        self.client.get(self.url)
        self.assertEqual(self.client.session[self.session_key], first)

    def test_time_taken_is_measured_from_opening_to_submitting(self):
        base = timezone.now()
        moment = {"now": base}
        with mock.patch("django.utils.timezone.now", side_effect=lambda: moment["now"]):
            self.client.get(self.url)
            moment["now"] = base + timedelta(seconds=125)
            self.submit()
        attempt = Attempt.objects.get()
        self.assertEqual(attempt.time_taken_sec, 125)
        self.assertEqual(attempt.submitted_at, base + timedelta(seconds=125))

    def test_submitting_removes_the_key_and_the_next_opening_starts_a_new_time(self):
        self.client.get(self.url)
        self.submit()
        self.assertNotIn(self.session_key, self.client.session)
        self.client.get(self.url)  # the page opens again after the redirect
        self.assertIn(self.session_key, self.client.session)

    def test_second_attempt_is_timed_from_the_new_opening(self):
        base = timezone.now()
        moment = {"now": base}
        with mock.patch("django.utils.timezone.now", side_effect=lambda: moment["now"]):
            self.client.get(self.url)
            moment["now"] = base + timedelta(seconds=100)
            self.submit(WRONG_CODE)
            self.client.get(self.url)  # reopened at +100 s
            moment["now"] = base + timedelta(seconds=130)
            self.submit()
        self.assertEqual(list(Attempt.objects.order_by("attempt_no").values_list("time_taken_sec", flat=True)), [100, 30])

    def test_submitting_without_opening_the_page_first_gives_zero_seconds(self):
        self.submit()
        self.assertEqual(Attempt.objects.get().time_taken_sec, 0)


class EmptySubmissionTests(ProblemPageTestBase):
    def test_empty_code_shows_a_message_and_saves_nothing(self):
        self.client.get(self.url)
        for code in ["", "   \r\n  "]:
            with self.subTest(code=repr(code)):
                response = self.submit(code)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Please write some code before submitting.")
                self.assertEqual(Attempt.objects.count(), 0)

    def test_empty_code_keeps_the_timer_running(self):
        self.client.get(self.url)
        first = self.client.session[self.session_key]
        self.submit("")
        self.assertEqual(self.client.session[self.session_key], first)

    def test_error_message_uses_the_shared_error_style(self):
        response = self.submit("")
        self.assertContains(response, "border-red-300")  # same red box as every other error

    @override_settings(MAX_SOURCE_CODE_CHARS=30)
    def test_too_long_code_is_rejected_and_kept_in_the_text_box(self):
        long_code = "print('hello world')  # " + "x" * 40
        response = self.submit(long_code)
        self.assertContains(response, "Your code is too long.")
        self.assertContains(response, "print(&#x27;hello world&#x27;)")  # the student's code is still there
        self.assertEqual(Attempt.objects.count(), 0)


class SubmissionFlowTests(ProblemPageTestBase):
    def test_submitting_saves_the_attempt_and_goes_to_the_result(self):
        response = self.submit()
        attempt = Attempt.objects.get()
        self.assertRedirects(response, f"{self.url}?attempt={attempt.pk}#result", fetch_redirect_response=False)
        self.assertEqual(attempt.student, self.student)
        self.assertEqual(attempt.problem, self.problem)
        self.assertEqual(attempt.attempt_no, 1)
        self.assertEqual(attempt.results.count(), 5)

    def test_correct_solution_is_marked_correct(self):
        self.submit(SUM_CODE)
        attempt = Attempt.objects.get()
        self.assertTrue(attempt.is_correct)
        self.assertEqual((attempt.tests_passed, attempt.tests_total), (5, 5))

    def test_wrong_solution_is_marked_incorrect(self):
        self.submit(WRONG_CODE)
        attempt = Attempt.objects.get()
        self.assertFalse(attempt.is_correct)
        self.assertEqual(attempt.tests_passed, 0)

    def test_attempt_numbers_increase_with_every_submit(self):
        for _ in range(3):
            self.submit(WRONG_CODE)
        self.assertEqual(list(Attempt.objects.order_by("id").values_list("attempt_no", flat=True)), [1, 2, 3])

    def test_attempt_copies_the_difficulty(self):
        self.submit()
        self.assertEqual(Attempt.objects.get().difficulty, "Easy")

    def test_problem_list_shows_solved_after_a_correct_submit(self):
        self.submit(SUM_CODE)
        rows = {row.problem.title: row.status for row in self.client.get(reverse("problems")).context["rows"]}
        self.assertEqual(rows["Sum of Array"], "solved")

    def test_submitting_needs_login(self):
        self.client.logout()
        response = self.submit()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
        self.assertEqual(Attempt.objects.count(), 0)

    def test_submit_form_needs_the_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.student)
        response = strict.post(self.url, {"source_code": SUM_CODE})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attempt.objects.count(), 0)

    def test_reloading_the_result_page_does_not_submit_again(self):
        response = self.submit()
        self.client.get(response.url)
        self.client.get(response.url)
        self.assertEqual(Attempt.objects.count(), 1)


class ResultSectionTests(ProblemPageTestBase):
    def open_result(self, code):
        response = self.submit(code)
        return self.client.get(response.url)

    def test_result_shows_every_test_case_and_the_total(self):
        page = self.open_result(SUM_CODE)
        self.assertContains(page, "Result of attempt #1")
        self.assertContains(page, "5 of 5")
        for number in range(1, 6):
            self.assertContains(page, f"Test case {number}")
        self.assertContains(page, "(sample)", count=2)
        self.assertContains(page, "(hidden)", count=3)
        self.assertContains(page, "Passed")

    def test_wrong_output_shows_failed(self):
        page = self.open_result(WRONG_CODE)
        self.assertContains(page, "0 of 5")
        self.assertContains(page, "Failed")
        self.assertContains(page, "output was not the expected output")

    def test_error_shows_the_error_message(self):
        page = self.open_result("print(1 / 0)\n")
        self.assertContains(page, "Error")
        self.assertContains(page, "ZeroDivisionError")
        self.assertContains(page, "division by zero")

    def test_syntax_error_shows_the_message(self):
        page = self.open_result("print('oops'\n")
        self.assertContains(page, "SyntaxError")

    @override_settings(CODE_TIME_LIMIT_SEC=1)
    def test_infinite_loop_shows_time_limit_exceeded(self):
        problem = make_problem("Loop me")
        for number in range(2):
            ProblemTestCase.objects.create(problem=problem, input_data="", expected_output="x", is_sample=number == 0)
        url = reverse("problem_detail", args=[problem.pk])
        response = self.client.post(url, {"source_code": "while True:\n    pass\n"})
        page = self.client.get(response.url)
        self.assertContains(page, "Time limit exceeded", count=4)  # 2 test cases, each with a label and a note
        self.assertContains(page, "Time limit exceeded (limit: 1 s).", count=2)
        self.assertContains(page, "0 of 2")

    def test_mixed_results_are_shown_test_case_by_test_case(self):
        code = (
            "n = int(input())\nnums = list(map(int, input().split()))\n"
            "print(nums[1] if n == 1 else sum(nums))\n"
        )
        page = self.open_result(code)
        self.assertContains(page, "4 of 5")
        self.assertContains(page, "IndexError")

    def test_result_does_not_show_hidden_test_data(self):
        page = self.open_result(SUM_CODE)
        # Hidden test cases of "Sum of Array" include this input and answer.
        self.assertNotContains(page, "1000 -1000 500 500 -250 250")

    def test_result_links_to_the_attempt_history(self):
        page = self.open_result(SUM_CODE)
        self.assertContains(page, "See all my attempts for this problem")
        self.assertContains(page, reverse("attempt_history", args=[self.problem.pk]))

    def test_submitted_code_is_shown_again_in_the_text_box(self):
        page = self.open_result("print('mine')  # my special comment\n")
        self.assertContains(page, "my special comment")

    def test_submitted_code_cannot_inject_html(self):
        page = self.open_result("</textarea><script>alert('hacked')</script>\n")
        self.assertNotContains(page, "<script>alert('hacked')")
        self.assertContains(page, "&lt;/textarea&gt;&lt;script&gt;")

    def test_result_shows_time_taken(self):
        base = timezone.now()
        moment = {"now": base}
        with mock.patch("django.utils.timezone.now", side_effect=lambda: moment["now"]):
            self.client.get(self.url)
            moment["now"] = base + timedelta(seconds=200)
            response = self.submit()
        self.assertContains(self.client.get(response.url), "3 min 20 s")


class OwnAttemptsOnlyTests(ProblemPageTestBase):
    def setUp(self):
        super().setUp()
        self.other = make_student("other@example.com")
        self.other_attempt = make_attempt(
            self.other, self.problem, attempt_no=1, is_correct=True, tests_passed=4, tests_total=9,
            source_code="print('OTHER-STUDENTS-SECRET-CODE')",
        )

    def test_another_students_attempt_in_the_url_is_ignored(self):
        page = self.client.get(f"{self.url}?attempt={self.other_attempt.pk}")
        self.assertEqual(page.status_code, 200)
        self.assertIsNone(page.context["attempt"])
        self.assertNotContains(page, "OTHER-STUDENTS-SECRET-CODE")
        self.assertNotContains(page, "4 of 9")
        self.assertNotContains(page, "Result of attempt")

    def test_own_attempt_in_the_url_is_shown(self):
        mine = make_attempt(self.student, self.problem, attempt_no=1, tests_passed=2, tests_total=5)
        page = self.client.get(f"{self.url}?attempt={mine.pk}")
        self.assertContains(page, "2 of 5")

    def test_attempt_of_a_different_problem_is_ignored(self):
        other_problem = Problem.objects.get(title="Palindrome Check")
        mine = make_attempt(self.student, other_problem, attempt_no=1, tests_passed=1, tests_total=5)
        page = self.client.get(f"{self.url}?attempt={mine.pk}")
        self.assertIsNone(page.context["attempt"])

    def test_wrong_attempt_values_in_the_url_do_not_crash(self):
        for value in ["abc", "", "-1", "99999999", "1.5", "1;DROP TABLE"]:
            with self.subTest(value=value):
                self.assertEqual(self.client.get(self.url, {"attempt": value}).status_code, 200)

    def test_submitting_does_not_touch_the_other_students_attempts(self):
        self.submit(SUM_CODE)
        self.assertEqual(Attempt.objects.for_student(self.other).count(), 1)
        mine = Attempt.objects.for_student(self.student).get()
        self.assertEqual(mine.attempt_no, 1)  # the other student's attempt #1 is not counted


class RecommendationCardTests(ProblemPageTestBase):
    """The suggestion shown under the result of a submission (Step 8)."""

    def result_page(self, code=SUM_CODE):
        response = self.submit(code)
        return self.client.get(response.url)

    def test_card_shows_the_activity_the_reason_and_a_button(self):
        page = self.result_page()
        reverse_array = Problem.objects.get(title="Reverse an Array")
        self.assertContains(page, "Recommended next")
        self.assertContains(page, "Same level")
        self.assertContains(page, "Reverse an Array")
        self.assertContains(page, "same level")  # part of the reason in plain language
        self.assertContains(page, "Open this problem")
        self.assertContains(page, f'href="{reverse("problem_detail", args=[reverse_array.pk])}"')

    def test_the_button_opens_the_recommended_problem(self):
        page = self.result_page()
        recommended = Recommendation.objects.get().problem
        opened = self.client.get(reverse("problem_detail", args=[recommended.pk]))
        self.assertEqual(opened.status_code, 200)
        self.assertContains(opened, recommended.title)

    def test_card_says_it_is_only_a_suggestion_and_links_to_all_problems(self):
        page = self.result_page()
        self.assertContains(page, "only a suggestion")
        self.assertContains(page, "Choose any other problem")
        self.assertContains(page, f'href="{reverse("problems")}"')

    def test_card_is_not_shown_before_anything_is_submitted(self):
        Recommendation.objects.create(student=self.student, activity="SAME", problem=self.problem, reason="Old")
        self.assertNotContains(self.client.get(self.url), "Recommended next")

    def test_every_submission_stores_one_recommendation_and_the_newest_is_shown(self):
        self.result_page(WRONG_CODE)
        page = self.result_page(SUM_CODE)
        self.assertEqual(Recommendation.objects.filter(student=self.student).count(), 2)
        newest = Recommendation.objects.for_student(self.student).first()
        self.assertContains(page, newest.reason)

    def test_another_students_recommendation_is_never_shown(self):
        other = make_student("other@example.com")
        Recommendation.objects.create(
            student=other, activity="HARDER", problem=Problem.objects.get(title="Count Inversions"),
            reason="OTHER-STUDENTS-PRIVATE-REASON",
        )
        page = self.result_page()
        self.assertNotContains(page, "OTHER-STUDENTS-PRIVATE-REASON")
        self.assertNotContains(page, "Count Inversions")

    def test_card_without_a_problem_links_to_the_topic(self):
        self.submit()
        Recommendation.objects.create(
            student=self.student, activity="NEXT_TOPIC", topic=Topic.objects.get(name="Strings"), reason="Move on."
        )
        page = self.client.get(f"{self.url}?attempt={Attempt.objects.get().pk}")
        self.assertContains(page, "See problems in Strings")
        self.assertNotContains(page, "Open this problem")

    def test_card_without_problem_and_topic_links_to_the_roadmap(self):
        self.submit()
        Recommendation.objects.create(student=self.student, activity="NEXT_TOPIC", reason="Nothing yet.")
        page = self.client.get(f"{self.url}?attempt={Attempt.objects.get().pk}")
        self.assertContains(page, "Open the roadmap")

    def test_a_failing_engine_does_not_break_the_submission_or_the_result_page(self):
        with mock.patch.object(RecommendationEngine, "recommend", side_effect=RuntimeError("boom")):
            with self.assertLogs("web.submission", level="ERROR"):
                response = self.submit()
        page = self.client.get(response.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "5 of 5")  # the result is there
        self.assertNotContains(page, "Recommended next")  # only the suggestion is missing

    def test_the_student_can_still_open_and_submit_any_problem(self):
        self.result_page()
        recommended = Recommendation.objects.get().problem
        other = Problem.objects.exclude(pk__in=[recommended.pk, self.problem.pk]).first()
        url = reverse("problem_detail", args=[other.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"source_code": "print(1)"}).status_code, 302)
        self.assertEqual(Attempt.objects.filter(problem=other).count(), 1)

    def test_revision_card_offers_a_problem_that_was_solved_before(self):
        """Arrays was strong but is forgotten; the student now practises Strings, so Arrays is suggested for revision."""
        from datetime import timedelta as delta

        long_ago = timezone.now() - delta(days=30)
        for number in range(3):
            make_attempt(self.student, self.problem, attempt_no=number + 1, is_correct=True, submitted_at=long_ago)
        palindrome = Problem.objects.get(title="Palindrome Check")
        code = "s = input()\nprint('YES' if s == s[::-1] else 'NO')\n"
        response = self.client.post(reverse("problem_detail", args=[palindrome.pk]), {"source_code": code})
        page = self.client.get(response.url)

        recommendation = Recommendation.objects.for_student(self.student).first()
        self.assertEqual(recommendation.activity, "REVISION")
        self.assertEqual(recommendation.problem, self.problem)  # solved before, on purpose
        self.assertContains(page, "Revision")
        self.assertContains(page, "over 14 days")
        self.assertContains(page, f'href="{reverse("problem_detail", args=[self.problem.pk])}"')
