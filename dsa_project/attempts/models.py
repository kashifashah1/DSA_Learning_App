"""Tables attempts_attempt and attempts_testcaseresult.

Every submission a student makes is stored as one Attempt, with one
TestCaseResult for each test case that was run.

Attempts are INSERT-ONLY: once saved they can never be edited or deleted
through Django code (the history must stay true). Students have no edit or
delete pages at all; this protection also stops mistakes in our own code.
(Storing the attempts is wired in Step 6.)
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from problems.models import Problem, TestCase


class InsertOnlyError(Exception):
    """Raised when code tries to change or delete a row that is insert-only."""


class InsertOnlyQuerySet(models.QuerySet):
    """Blocks the "many rows at once" ways of editing or deleting."""

    def update(self, **kwargs):
        raise InsertOnlyError("These rows cannot be edited.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise InsertOnlyError("These rows cannot be edited.")

    def delete(self):
        raise InsertOnlyError("These rows cannot be deleted.")


class InsertOnlyModel(models.Model):
    """Base class for rows that may be inserted but never edited or deleted."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise InsertOnlyError(f"A saved {type(self).__name__} cannot be edited.")
        # force_insert makes sure we never overwrite an existing row that has the same id.
        kwargs["force_insert"] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise InsertOnlyError(f"A {type(self).__name__} cannot be deleted.")


class AttemptQuerySet(InsertOnlyQuerySet):
    def for_student(self, student):
        """The only way pages should read attempts: always limited to one student.

        Pass the logged-in student (request.user). A missing or anonymous user
        gets nothing, so one student can never see another student's attempts.
        """
        if student is None or not getattr(student, "is_authenticated", False):
            return self.none()
        return self.filter(student=student)


class Attempt(InsertOnlyModel):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    # PROTECT: a problem that students already tried cannot be deleted by mistake.
    problem = models.ForeignKey(Problem, on_delete=models.PROTECT, related_name="attempts")
    source_code = models.TextField()
    difficulty = models.CharField(max_length=6, choices=Problem.Difficulty.choices)  # copied at attempt time
    is_correct = models.BooleanField()
    tests_passed = models.PositiveIntegerField()
    tests_total = models.PositiveIntegerField()
    attempt_no = models.PositiveIntegerField()  # 1 for the first try of this problem, 2 for the second, ...
    time_taken_sec = models.PositiveIntegerField()
    exec_time_ms = models.PositiveIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(default=timezone.now)

    objects = AttemptQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "problem", "attempt_no"], name="unique_attempt_no_per_student_problem"
            ),
        ]
        indexes = [
            models.Index(fields=["student", "submitted_at"], name="attempt_student_time_idx"),
        ]

    def __str__(self):
        result = "correct" if self.is_correct else "wrong"
        return f"{self.student} / {self.problem} / try {self.attempt_no} ({result})"

    @property
    def time_taken_display(self):
        """Time taken in words, for example "45 s" or "3 min 20 s"."""
        minutes, seconds = divmod(self.time_taken_sec, 60)
        return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"

    @property
    def exec_time_display(self):
        return "Not available" if self.exec_time_ms is None else f"{self.exec_time_ms} ms"


class TestCaseResult(InsertOnlyModel):
    """The result of running one test case for one attempt."""

    class Status(models.TextChoices):
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"
        TLE = "TLE", "Time limit exceeded"
        ERROR = "ERROR", "Error"

    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="results")
    # SET_NULL: if the administrator deletes a test case, old results stay (without the link).
    test_case = models.ForeignKey(TestCase, on_delete=models.SET_NULL, null=True, blank=True, related_name="results")
    status = models.CharField(max_length=6, choices=Status.choices)
    exec_time_ms = models.PositiveIntegerField()
    error_message = models.TextField(blank=True, default="")

    objects = InsertOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.attempt} / {self.status}"
