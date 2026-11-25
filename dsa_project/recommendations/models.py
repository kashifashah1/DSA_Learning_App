"""Table recommendations_recommendation: what the system suggested to a student, and why."""

from django.conf import settings
from django.db import models

from problems.models import Problem, Topic


class RecommendationQuerySet(models.QuerySet):
    def for_student(self, student):
        """Recommendations of one student only (a student never sees another student's)."""
        if student is None or not getattr(student, "is_authenticated", False):
            return self.none()
        return self.filter(student=student)


class Recommendation(models.Model):
    class Activity(models.TextChoices):
        EASIER = "EASIER", "Easier problem"
        SAME = "SAME", "Same level"
        HARDER = "HARDER", "Harder problem"
        RELATED = "RELATED", "Related practice"
        REVISION = "REVISION", "Revision"
        NEXT_TOPIC = "NEXT_TOPIC", "Next topic"

    class Source(models.TextChoices):
        RULE = "RULE", "Rule-based"
        MODEL_ASSISTED = "MODEL_ASSISTED", "Model-assisted"

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendations")
    activity = models.CharField(max_length=10, choices=Activity.choices)
    problem = models.ForeignKey(Problem, null=True, blank=True, on_delete=models.SET_NULL, related_name="recommendations")
    topic = models.ForeignKey(Topic, null=True, blank=True, on_delete=models.SET_NULL, related_name="recommendations")
    reason = models.TextField()  # plain-language explanation shown to the student
    source = models.CharField(max_length=14, choices=Source.choices, default=Source.RULE)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RecommendationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]  # newest first

    def __str__(self):
        return f"{self.student} / {self.activity} / {self.problem}"
