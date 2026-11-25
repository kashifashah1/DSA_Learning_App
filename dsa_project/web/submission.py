"""Submitting a solution: SubmissionService and SolveTimer.

The view only collects what the student typed; everything that decides what is saved
is here, so it can be tested without a browser.
"""

import logging
from datetime import datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from analytics.services import PerformanceAnalyzer
from attempts.evaluator import CodeEvaluator
from attempts.models import Attempt, TestCaseResult
from recommendations.engine import RecommendationEngine

logger = logging.getLogger(__name__)


class SubmissionError(Exception):
    """A submission that cannot be accepted. The message is written for the student."""


class SolveTimer:
    """Remembers in the Django session when a student opened a problem.

    The session key is made from the problem id, so every problem has its own timer.
    """

    def __init__(self, session, problem_id, clock=None):
        self.session = session
        self.key = f"problem_opened_{problem_id}"
        self.clock = clock or timezone.now

    def start(self):
        """Store the opening time. If it is already stored (page reloaded), keep the first one."""
        if self.key not in self.session:
            self.session[self.key] = self.clock().isoformat()

    def opened_at(self):
        """The stored opening time, or None if there is none (or it is damaged)."""
        value = self.session.get(self.key)
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def clear(self):
        """Remove the stored time. The next time the page opens, a new one is stored."""
        self.session.pop(self.key, None)


class SubmissionService:
    """Checks a submission, runs it on ALL test cases and stores the attempt."""

    def __init__(self, evaluator=None, clock=None):
        self.evaluator = evaluator or CodeEvaluator()
        self.clock = clock or timezone.now

    def submit(self, student, problem, source_code, opened_at=None):
        """Evaluate the code and store one Attempt with its TestCaseResults. Returns the Attempt.

        opened_at: when the student opened the problem page (None if unknown).
        Raises SubmissionError (nothing is saved) if the submission is not acceptable.
        """
        source_code = source_code.replace("\r\n", "\n")  # browsers send \r\n in text boxes
        self._check_code(source_code)
        test_cases = list(problem.test_cases.all())
        if not test_cases:
            raise SubmissionError("This problem has no test cases yet, so it cannot be checked.")

        now = self.clock()  # the moment of submitting (running the code is not counted)
        time_taken_sec = self._seconds_between(opened_at, now)

        # Always ALL test cases (sample and hidden). This can take a few seconds.
        results = self.evaluator.evaluate(source_code, test_cases)

        attempt = self._save(student, problem, source_code, test_cases, results, time_taken_sec, now)
        self._after_save(attempt)
        return attempt

    # --------------------------------------------------------------- checking
    @staticmethod
    def _check_code(source_code):
        if not source_code.strip():
            raise SubmissionError("Please write some code before submitting.")
        if len(source_code) > settings.MAX_SOURCE_CODE_CHARS:
            raise SubmissionError(
                f"Your code is too long. The limit is {settings.MAX_SOURCE_CODE_CHARS} characters."
            )

    @staticmethod
    def _seconds_between(opened_at, now):
        """Whole seconds from opening the page to submitting. 0 if the opening time is unknown."""
        if opened_at is None:
            return 0
        return max(int((now - opened_at).total_seconds()), 0)

    # ----------------------------------------------------------------- saving
    def _save(self, student, problem, source_code, test_cases, results, time_taken_sec, now):
        passed = CodeEvaluator.tests_passed(results)
        # The slowest single test case: how long one run of the solution really takes.
        exec_time_ms = max(result.exec_time_ms for result in results)

        for try_number in range(3):
            try:
                with transaction.atomic():
                    attempt = Attempt.objects.create(
                        student=student,
                        problem=problem,
                        source_code=source_code,
                        difficulty=problem.difficulty,  # copied now: it may be changed later
                        is_correct=CodeEvaluator.is_correct(results),  # only if ALL test cases passed
                        tests_passed=passed,
                        tests_total=len(results),
                        attempt_no=self._next_attempt_no(student, problem),
                        time_taken_sec=time_taken_sec,
                        exec_time_ms=exec_time_ms,
                        submitted_at=now,
                    )
                    TestCaseResult.objects.bulk_create(
                        [
                            TestCaseResult(
                                attempt=attempt,
                                test_case=test_case,
                                status=result.status,
                                exec_time_ms=result.exec_time_ms,
                                error_message=result.error_message,
                            )
                            for test_case, result in zip(test_cases, results)
                        ]
                    )
                return attempt
            except IntegrityError:
                # Two submissions of the same student arrived at the same moment (double click)
                # and took the same attempt number. Count again and try once more.
                if try_number == 2:
                    raise
                logger.warning("Attempt number was already taken, trying again")

    @staticmethod
    def _next_attempt_no(student, problem):
        """Previous attempts of this student for this problem, plus one."""
        return Attempt.objects.for_student(student).filter(problem=problem).count() + 1

    # ------------------------------------------------------------------ hooks
    def _after_save(self, attempt):
        """Work that follows a saved attempt. A problem here must never lose the attempt,
        and a problem in one step must not stop the next one."""
        for step in (self.update_performance, self.make_recommendation):
            try:
                step(attempt)
            except Exception:
                logger.exception("%s failed after saving attempt %s", getattr(step, "__name__", "A step"), attempt.pk)

    def update_performance(self, attempt):
        """Step 7: recalculate and store ONLY the topic of this attempt (for this student)."""
        PerformanceAnalyzer().update_topic_performance(attempt.student, attempt.problem.subtopic.topic)

    def make_recommendation(self, attempt):
        """Step 8: decide and store what the student should practise next."""
        RecommendationEngine().recommend(attempt.student)
