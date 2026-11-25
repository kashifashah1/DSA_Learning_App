"""Problem catalogue: Topic -> Subtopic -> Problem -> TestCase.

The administrator adds and edits all of this in the Django admin site, so a new
topic or problem never needs a code change.
"""

from django.db import models


class Topic(models.Model):
    name = models.CharField(max_length=100, unique=True)
    order = models.PositiveIntegerField(default=0)  # position in the roadmap

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Subtopic(models.Model):
    # PROTECT: a topic that still has subtopics cannot be deleted by mistake.
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, related_name="subtopics")
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["topic__order", "order", "name"]
        constraints = [
            # The same subtopic name may exist in different topics, but only once per topic.
            models.UniqueConstraint(fields=["topic", "name"], name="unique_subtopic_name_per_topic"),
        ]

    def __str__(self):
        return f"{self.topic.name} / {self.name}"


class Problem(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "Easy", "Easy"
        MEDIUM = "Medium", "Medium"
        HARD = "Hard", "Hard"

    title = models.CharField(max_length=200)
    statement = models.TextField()
    difficulty = models.CharField(max_length=6, choices=Difficulty.choices)
    # PROTECT: a subtopic that still has problems cannot be deleted by mistake.
    subtopic = models.ForeignKey(Subtopic, on_delete=models.PROTECT, related_name="problems")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["subtopic__topic__order", "subtopic__order", "id"]

    @property
    def topic(self):
        """The topic is reached through the subtopic (it is not stored twice)."""
        return self.subtopic.topic

    def is_attempted_by(self, student):
        """True if the student has submitted at least one attempt (right or wrong).
        Uses the reverse relation `attempts` created by attempts.Attempt."""
        return self.attempts.filter(student=student).exists()

    def is_solved_by(self, student):
        """True if at least one attempt of this student passed all test cases."""
        return self.attempts.filter(student=student, is_correct=True).exists()

    def __str__(self):
        return self.title


class TestCase(models.Model):
    """One input/expected-output pair. Sample test cases are shown to students."""

    # CASCADE: test cases belong to the problem, so they go away with it.
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name="test_cases")
    input_data = models.TextField()  # given to the program on standard input
    expected_output = models.TextField()  # what the program must print
    is_sample = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        kind = "sample" if self.is_sample else "hidden"
        return f"{self.problem.title} ({kind} test #{self.pk})"
