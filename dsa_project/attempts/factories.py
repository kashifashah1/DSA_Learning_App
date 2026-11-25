"""Helpers that build test data for the analytics and recommendation tests."""

from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

from problems.models import Problem, Subtopic, Topic

from .models import Attempt

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=dt_timezone.utc)


def make_catalogue():
    """A small roadmap with known problems. Topics are created in the "wrong" order on purpose.

        Arrays (order 1)   Traversal (1): easy1, easy2, medium, hard      Two Pointers (2): tp_easy, tp_medium
        Strings (order 2)  Basics (1): s_easy, s_medium
        Graphs (order 3)   Intro (1): g_easy, g_hard
    """
    graphs = Topic.objects.create(name="Graphs", order=3)
    strings = Topic.objects.create(name="Strings", order=2)
    arrays = Topic.objects.create(name="Arrays", order=1)
    traversal = Subtopic.objects.create(topic=arrays, name="Traversal", order=1)
    pointers = Subtopic.objects.create(topic=arrays, name="Two Pointers", order=2)
    basics = Subtopic.objects.create(topic=strings, name="Basics", order=1)
    intro = Subtopic.objects.create(topic=graphs, name="Intro", order=1)

    def problem(title, difficulty, subtopic):
        return Problem.objects.create(title=title, statement="S", difficulty=difficulty, subtopic=subtopic)

    return SimpleNamespace(
        arrays=arrays, strings=strings, graphs=graphs,
        traversal=traversal, pointers=pointers, basics=basics, intro=intro,
        easy1=problem("Easy 1", "Easy", traversal), easy2=problem("Easy 2", "Easy", traversal),
        medium=problem("Medium", "Medium", traversal), hard=problem("Hard", "Hard", traversal),
        tp_easy=problem("TP Easy", "Easy", pointers), tp_medium=problem("TP Medium", "Medium", pointers),
        s_easy=problem("S Easy", "Easy", basics), s_medium=problem("S Medium", "Medium", basics),
        g_easy=problem("G Easy", "Easy", intro), g_hard=problem("G Hard", "Hard", intro),
    )


class AttemptLog:
    """Adds attempts one after the other. Time moves forward by 10 minutes with every attempt,
    starting from `days_ago` days before NOW (use .at() to jump to another moment)."""

    def __init__(self, student, days_ago=1):
        self.student = student
        self.moment = NOW - timedelta(days=days_ago)

    def at(self, days_ago=0, minutes_ago=0):
        self.moment = NOW - timedelta(days=days_ago, minutes=minutes_ago)
        return self

    def add(self, problem, correct, secs=60):
        number = Attempt.objects.filter(student=self.student, problem=problem).count() + 1
        self.moment += timedelta(minutes=10)
        return Attempt.objects.create(
            student=self.student, problem=problem, source_code="x", difficulty=problem.difficulty,
            is_correct=correct, tests_passed=3 if correct else 1, tests_total=3, attempt_no=number,
            time_taken_sec=secs, exec_time_ms=10, submitted_at=self.moment,
        )

    def many(self, problem, outcomes, secs=60):
        """outcomes: for example "CFC" = correct, failed, correct."""
        return [self.add(problem, letter == "C", secs) for letter in outcomes]
