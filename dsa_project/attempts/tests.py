"""Tests for the Attempt table and the Problem.is_attempted_by / is_solved_by methods."""

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from problems.models import Problem, Subtopic, Topic
from users.models import User

from .models import Attempt


def make_problem(title="Sum"):
    topic, _ = Topic.objects.get_or_create(name="Arrays")
    subtopic, _ = Subtopic.objects.get_or_create(topic=topic, name="Basics")
    return Problem.objects.create(title=title, statement="S", difficulty="Easy", subtopic=subtopic)


def make_student(email="sam@example.com"):
    return User.objects.create_user(email=email, name="Sam", password="Strong#Pass123")


def make_attempt(student, problem, attempt_no=1, is_correct=False, **extra):
    values = dict(
        student=student,
        problem=problem,
        source_code="print(1)",
        difficulty=problem.difficulty,
        is_correct=is_correct,
        tests_passed=3 if is_correct else 1,
        tests_total=3,
        attempt_no=attempt_no,
        time_taken_sec=60,
    )
    values.update(extra)
    return Attempt.objects.create(**values)


class AttemptModelTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.problem = make_problem()

    def test_attempt_number_is_unique_per_student_and_problem(self):
        make_attempt(self.student, self.problem, attempt_no=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_attempt(self.student, self.problem, attempt_no=1)

    def test_same_attempt_number_is_fine_for_another_student_or_problem(self):
        make_attempt(self.student, self.problem, attempt_no=1)
        make_attempt(make_student("other@example.com"), self.problem, attempt_no=1)
        make_attempt(self.student, make_problem("Other problem"), attempt_no=1)
        self.assertEqual(Attempt.objects.count(), 3)

    def test_exec_time_can_be_empty(self):
        attempt = make_attempt(self.student, self.problem, exec_time_ms=None)
        attempt.refresh_from_db()
        self.assertIsNone(attempt.exec_time_ms)

    def test_submitted_at_is_filled_automatically(self):
        self.assertIsNotNone(make_attempt(self.student, self.problem).submitted_at)

    def test_problem_with_attempts_cannot_be_deleted(self):
        make_attempt(self.student, self.problem)
        with self.assertRaises(ProtectedError):
            self.problem.delete()


class ProblemStatusMethodTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.problem = make_problem()

    def test_new_problem_is_not_attempted_and_not_solved(self):
        self.assertFalse(self.problem.is_attempted_by(self.student))
        self.assertFalse(self.problem.is_solved_by(self.student))

    def test_wrong_attempt_counts_as_attempted_but_not_solved(self):
        make_attempt(self.student, self.problem, is_correct=False)
        self.assertTrue(self.problem.is_attempted_by(self.student))
        self.assertFalse(self.problem.is_solved_by(self.student))

    def test_correct_attempt_counts_as_solved(self):
        make_attempt(self.student, self.problem, is_correct=True)
        self.assertTrue(self.problem.is_attempted_by(self.student))
        self.assertTrue(self.problem.is_solved_by(self.student))

    def test_solved_after_an_earlier_wrong_attempt(self):
        make_attempt(self.student, self.problem, attempt_no=1, is_correct=False)
        make_attempt(self.student, self.problem, attempt_no=2, is_correct=True)
        self.assertTrue(self.problem.is_solved_by(self.student))

    def test_other_students_attempts_do_not_count(self):
        other = make_student("other@example.com")
        make_attempt(other, self.problem, is_correct=True)
        self.assertFalse(self.problem.is_attempted_by(self.student))
        self.assertFalse(self.problem.is_solved_by(self.student))
