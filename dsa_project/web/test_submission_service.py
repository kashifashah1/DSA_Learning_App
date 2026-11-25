"""Unit tests for SubmissionService and SolveTimer (Step 6)."""

from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, override_settings

from attempts.evaluator import CodeEvaluator, Status, TestRunResult
from attempts.models import Attempt, TestCaseResult
from attempts.tests import make_attempt, make_problem, make_student
from problems.models import Problem
from problems.models import TestCase as ProblemTestCase
from recommendations.engine import RecommendationEngine
from recommendations.models import Recommendation

from .submission import SolveTimer, SubmissionError, SubmissionService

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=dt_timezone.utc)
CODE = "print(1)"


def clock():
    return NOW


def run(status=Status.PASSED, ms=10, error=""):
    return TestRunResult(status, "", ms, error)


class FakeEvaluator:
    """Gives scripted results, so these tests do not start any process."""

    def __init__(self, results=None):
        self.results = results
        self.calls = []

    def evaluate(self, source_code, test_cases):
        self.calls.append((source_code, list(test_cases)))
        return self.results if self.results is not None else [run() for _ in test_cases]


def add_cases(problem, count=3, samples=1):
    """Give the problem `count` test cases; the first `samples` are sample test cases."""
    for number in range(count):
        ProblemTestCase.objects.create(
            problem=problem, input_data=str(number), expected_output=str(number), is_sample=number < samples
        )
    return list(problem.test_cases.all())


class SubmissionServiceTestBase(TestCase):
    def setUp(self):
        self.student = make_student()
        self.problem = make_problem()
        self.cases = add_cases(self.problem, count=3, samples=1)
        self.evaluator = FakeEvaluator()
        self.service = SubmissionService(evaluator=self.evaluator, clock=clock)

    def submit(self, code=CODE, opened_at=None, student=None, problem=None):
        return self.service.submit(student or self.student, problem or self.problem, code, opened_at=opened_at)


class RejectedSubmissionTests(SubmissionServiceTestBase):
    def test_empty_code_is_rejected_with_a_message(self):
        for code in ["", "   ", "\n\n", " \t \r\n "]:
            with self.subTest(code=repr(code)):
                with self.assertRaises(SubmissionError) as caught:
                    self.submit(code)
                self.assertIn("write some code", str(caught.exception))

    def test_rejected_submission_saves_nothing_and_runs_nothing(self):
        with self.assertRaises(SubmissionError):
            self.submit("   ")
        self.assertEqual(Attempt.objects.count(), 0)
        self.assertEqual(TestCaseResult.objects.count(), 0)
        self.assertEqual(self.evaluator.calls, [])

    @override_settings(MAX_SOURCE_CODE_CHARS=50)
    def test_too_long_code_is_rejected(self):
        self.submit("x = 1\n" * 8)  # 48 characters: fine
        with self.assertRaises(SubmissionError) as caught:
            self.submit("x = 1\n" * 20)
        self.assertIn("too long", str(caught.exception))
        self.assertEqual(Attempt.objects.count(), 1)

    def test_problem_without_test_cases_is_rejected(self):
        empty_problem = make_problem("No tests")
        with self.assertRaises(SubmissionError) as caught:
            self.submit(problem=empty_problem)
        self.assertIn("no test cases", str(caught.exception))
        self.assertEqual(Attempt.objects.count(), 0)


class SavingTests(SubmissionServiceTestBase):
    def test_all_test_cases_are_run_sample_and_hidden(self):
        self.submit()
        source, cases = self.evaluator.calls[0]
        self.assertEqual(cases, self.cases)  # all three, in order
        self.assertEqual([c.is_sample for c in cases], [True, False, False])

    def test_attempt_is_saved_with_the_right_values(self):
        attempt = self.submit("print(2)\r\nprint(3)", opened_at=NOW - timedelta(seconds=40))
        saved = Attempt.objects.get()
        self.assertEqual(saved, attempt)
        self.assertEqual(saved.student, self.student)
        self.assertEqual(saved.problem, self.problem)
        self.assertEqual(saved.source_code, "print(2)\nprint(3)")  # line endings made equal
        self.assertEqual(saved.tests_total, 3)
        self.assertEqual(saved.submitted_at, NOW)

    def test_one_result_is_saved_for_every_test_case(self):
        self.evaluator.results = [
            run(Status.PASSED, 5),
            run(Status.FAILED, 6),
            run(Status.ERROR, 7, "Traceback ... ValueError"),
        ]
        attempt = self.submit()
        saved = list(attempt.results.all())
        self.assertEqual([r.test_case for r in saved], self.cases)
        self.assertEqual([r.status for r in saved], ["PASSED", "FAILED", "ERROR"])
        self.assertEqual([r.exec_time_ms for r in saved], [5, 6, 7])
        self.assertEqual(saved[2].error_message, "Traceback ... ValueError")
        self.assertEqual(saved[0].error_message, "")

    def test_time_limit_exceeded_is_saved_as_tle(self):
        self.evaluator.results = [run(Status.TLE, 5000, "Time limit exceeded (limit: 5 s)."), run(), run()]
        attempt = self.submit()
        self.assertEqual(attempt.results.first().status, "TLE")

    def test_difficulty_is_copied_at_the_time_of_the_attempt(self):
        attempt = self.submit()
        self.assertEqual(attempt.difficulty, "Easy")
        self.problem.difficulty = "Hard"
        self.problem.save()
        attempt.refresh_from_db()
        self.assertEqual(attempt.difficulty, "Easy")  # the attempt keeps what it was

    def test_execution_time_is_the_slowest_test_case(self):
        self.evaluator.results = [run(ms=5), run(ms=90), run(ms=7)]
        self.assertEqual(self.submit().exec_time_ms, 90)


class CorrectOrIncorrectTests(SubmissionServiceTestBase):
    def test_correct_only_if_every_test_case_passed(self):
        attempt = self.submit()
        self.assertTrue(attempt.is_correct)
        self.assertEqual((attempt.tests_passed, attempt.tests_total), (3, 3))

    def test_one_failed_test_case_makes_it_incorrect(self):
        self.evaluator.results = [run(), run(Status.FAILED), run()]
        attempt = self.submit()
        self.assertFalse(attempt.is_correct)
        self.assertEqual((attempt.tests_passed, attempt.tests_total), (2, 3))

    def test_timeout_or_error_also_make_it_incorrect(self):
        for bad in (Status.TLE, Status.ERROR):
            with self.subTest(bad=bad):
                self.evaluator.results = [run(), run(), run(bad)]
                attempt = self.submit()
                self.assertFalse(attempt.is_correct)
                self.assertEqual(attempt.tests_passed, 2)

    def test_nothing_passed(self):
        self.evaluator.results = [run(Status.ERROR)] * 3
        attempt = self.submit()
        self.assertFalse(attempt.is_correct)
        self.assertEqual(attempt.tests_passed, 0)


class AttemptNumberTests(SubmissionServiceTestBase):
    def test_numbers_go_1_2_3(self):
        self.assertEqual([self.submit().attempt_no for _ in range(3)], [1, 2, 3])

    def test_number_is_previous_attempts_plus_one(self):
        make_attempt(self.student, self.problem, attempt_no=1)
        make_attempt(self.student, self.problem, attempt_no=2)
        self.assertEqual(self.submit().attempt_no, 3)

    def test_other_students_attempts_are_not_counted(self):
        other = make_student("other@example.com")
        make_attempt(other, self.problem, attempt_no=1)
        make_attempt(other, self.problem, attempt_no=2)
        self.assertEqual(self.submit().attempt_no, 1)

    def test_other_problems_attempts_are_not_counted(self):
        other_problem = make_problem("Other")
        add_cases(other_problem)
        self.submit(problem=other_problem)
        self.submit(problem=other_problem)
        self.assertEqual(self.submit().attempt_no, 1)

    def test_two_submissions_at_the_same_moment_get_different_numbers(self):
        """A double click can make both submissions count the same number. The second one retries."""
        make_attempt(self.student, self.problem, attempt_no=1)
        with mock.patch.object(SubmissionService, "_next_attempt_no", side_effect=[1, 2]) as counted:
            with self.assertLogs("web.submission", level="WARNING"):
                attempt = self.submit()
        self.assertEqual(counted.call_count, 2)
        self.assertEqual(attempt.attempt_no, 2)
        self.assertEqual(Attempt.objects.count(), 2)
        self.assertEqual(TestCaseResult.objects.count(), 3)  # no half-saved results from the failed try


class TimeTakenTests(SubmissionServiceTestBase):
    def test_time_taken_is_now_minus_opening_time(self):
        attempt = self.submit(opened_at=NOW - timedelta(seconds=125))
        self.assertEqual(attempt.time_taken_sec, 125)

    def test_whole_seconds(self):
        attempt = self.submit(opened_at=NOW - timedelta(seconds=10, milliseconds=900))
        self.assertEqual(attempt.time_taken_sec, 10)

    def test_unknown_opening_time_gives_zero(self):
        self.assertEqual(self.submit(opened_at=None).time_taken_sec, 0)

    def test_opening_time_in_the_future_gives_zero_not_negative(self):
        self.assertEqual(self.submit(opened_at=NOW + timedelta(seconds=30)).time_taken_sec, 0)

    def test_running_the_code_is_not_counted(self):
        """The time is measured when the student submits, before the (slow) test runs."""
        moments = iter([NOW, NOW + timedelta(seconds=25)])
        service = SubmissionService(evaluator=self.evaluator, clock=lambda: next(moments))
        attempt = service.submit(self.student, self.problem, CODE, opened_at=NOW - timedelta(seconds=60))
        self.assertEqual(attempt.time_taken_sec, 60)


class HookTests(SubmissionServiceTestBase):
    def test_hooks_for_steps_7_and_8_are_called_after_the_attempt_is_saved(self):
        seen = {}

        def check(name):
            def hook(attempt):
                seen[name] = Attempt.objects.filter(pk=attempt.pk).exists()
            return hook

        with mock.patch.object(SubmissionService, "update_performance", side_effect=check("performance")) as perf, \
             mock.patch.object(SubmissionService, "make_recommendation", side_effect=check("recommendation")) as rec:
            attempt = self.submit()
        perf.assert_called_once_with(attempt)
        rec.assert_called_once_with(attempt)
        self.assertEqual(seen, {"performance": True, "recommendation": True})

    def test_a_failing_hook_never_loses_the_attempt(self):
        with mock.patch.object(SubmissionService, "update_performance", side_effect=RuntimeError("boom")):
            with self.assertLogs("web.submission", level="ERROR"):
                attempt = self.submit()
        self.assertTrue(Attempt.objects.filter(pk=attempt.pk).exists())

    def test_the_performance_hook_is_still_empty_until_step_7(self):
        self.assertIsNone(self.service.update_performance(self.submit()))

    def test_a_recommendation_is_stored_after_every_attempt(self):
        self.assertEqual(Recommendation.objects.count(), 0)
        attempt = self.submit()
        recommendation = Recommendation.objects.get()
        self.assertEqual(recommendation.student, attempt.student)
        self.assertEqual(recommendation.source, "RULE")
        self.assertTrue(recommendation.reason)
        self.submit()
        self.assertEqual(Recommendation.objects.count(), 2)  # one for each attempt

    def test_the_recommendation_sees_the_attempt_that_was_just_saved(self):
        """The hook runs after the attempt is stored, so the engine already counts it."""
        seen = {}
        real_recommend = RecommendationEngine.recommend

        def spy(engine, student):
            seen["attempts"] = Attempt.objects.for_student(student).count()
            return real_recommend(engine, student)

        with mock.patch.object(RecommendationEngine, "recommend", spy):
            self.submit()
        self.assertEqual(seen["attempts"], 1)

    def test_a_failing_recommendation_engine_never_loses_the_attempt(self):
        with mock.patch.object(RecommendationEngine, "recommend", side_effect=RuntimeError("boom")):
            with self.assertLogs("web.submission", level="ERROR"):
                attempt = self.submit()
        self.assertTrue(Attempt.objects.filter(pk=attempt.pk).exists())
        self.assertEqual(attempt.results.count(), 3)


class RealEvaluatorTests(TestCase):
    """The service together with the real CodeEvaluator (separate processes)."""

    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student()
        self.problem = Problem.objects.get(title="Sum of Array")
        self.service = SubmissionService()

    def test_correct_solution_is_stored_as_correct(self):
        code = "input()\nprint(sum(map(int, input().split())))\n"
        attempt = self.service.submit(self.student, self.problem, code)
        self.assertTrue(attempt.is_correct)
        self.assertEqual((attempt.tests_passed, attempt.tests_total), (5, 5))
        self.assertEqual(set(attempt.results.values_list("status", flat=True)), {"PASSED"})

    def test_wrong_solution_is_stored_as_incorrect(self):
        code = "input()\nprint(sum(map(int, input().split())) + 1)\n"
        attempt = self.service.submit(self.student, self.problem, code)
        self.assertFalse(attempt.is_correct)
        self.assertEqual(attempt.tests_passed, 0)
        self.assertEqual(set(attempt.results.values_list("status", flat=True)), {"FAILED"})

    def test_mixed_results_run_every_test_case(self):
        code = (  # crashes only for n == 1
            "n = int(input())\nnums = list(map(int, input().split()))\n"
            "print(nums[1] if n == 1 else sum(nums))\n"
        )
        attempt = self.service.submit(self.student, self.problem, code)
        statuses = list(attempt.results.values_list("status", flat=True))
        self.assertEqual(len(statuses), 5)
        self.assertEqual(statuses.count("ERROR"), 1)
        self.assertEqual(statuses.count("PASSED"), 4)
        self.assertFalse(attempt.is_correct)
        self.assertIn("IndexError", attempt.results.get(status="ERROR").error_message)

    @override_settings(CODE_TIME_LIMIT_SEC=1)
    def test_infinite_loop_is_stored_as_tle(self):
        code = "n = int(input())\nif n == 1:\n    while True:\n        pass\nprint(sum(map(int, input().split())))\n"
        attempt = self.service.submit(self.student, self.problem, code)
        statuses = list(attempt.results.values_list("status", flat=True))
        self.assertEqual(statuses.count("TLE"), 1)
        self.assertEqual(statuses.count("PASSED"), 4)  # the other test cases still ran
        self.assertFalse(attempt.is_correct)


class SolveTimerTests(TestCase):
    def setUp(self):
        self.session = {}
        self.timer = SolveTimer(self.session, 7, clock=clock)

    def test_start_stores_the_opening_time_under_a_key_with_the_problem_id(self):
        self.timer.start()
        self.assertEqual(list(self.session), ["problem_opened_7"])
        self.assertEqual(self.timer.opened_at(), NOW)

    def test_different_problems_have_different_keys(self):
        SolveTimer(self.session, 8, clock=clock).start()
        self.timer.start()
        self.assertEqual(sorted(self.session), ["problem_opened_7", "problem_opened_8"])

    def test_opening_the_page_again_keeps_the_first_time(self):
        self.timer.start()
        later = SolveTimer(self.session, 7, clock=lambda: NOW + timedelta(minutes=5))
        later.start()
        self.assertEqual(later.opened_at(), NOW)

    def test_clear_removes_the_key(self):
        self.timer.start()
        self.timer.clear()
        self.assertEqual(self.session, {})
        self.assertIsNone(self.timer.opened_at())

    def test_clearing_when_there_is_nothing_is_fine(self):
        self.timer.clear()
        self.assertEqual(self.session, {})

    def test_damaged_value_counts_as_unknown(self):
        self.session["problem_opened_7"] = "not a date"
        self.assertIsNone(self.timer.opened_at())

    def test_after_clear_the_next_start_stores_a_new_time(self):
        self.timer.start()
        self.timer.clear()
        later = SolveTimer(self.session, 7, clock=lambda: NOW + timedelta(minutes=5))
        later.start()
        self.assertEqual(later.opened_at(), NOW + timedelta(minutes=5))
