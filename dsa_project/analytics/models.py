"""Table analytics_topicperformance: one stored row per student and topic.

The row is a saved copy of the numbers that PerformanceAnalyzer calculates from the
student's attempts. It is rewritten (only for that student and topic) after every attempt.
The attempts stay the source of truth: `python manage.py rebuild_performance` can rebuild
every row from them at any time.
"""

from django.conf import settings
from django.db import models

from problems.models import Topic


class TopicPerformance(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="topic_performances")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="performances")
    total_attempts = models.PositiveIntegerField(default=0)
    accuracy = models.FloatField(default=0)  # 0 to 1
    recent_accuracy = models.FloatField(default=0)  # 0 to 1, last RECENT_WINDOW attempts
    avg_time_sec = models.FloatField(default=0)
    avg_attempts = models.FloatField(default=0)  # attempts per problem tried
    mastery_score = models.FloatField(null=True, blank=True)  # 0 to 100; empty if not enough data
    learning_level = models.CharField(max_length=20)  # Beginner / Intermediate / Advanced / Not enough data
    last_practised = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "topic"], name="unique_performance_per_student_topic"),
        ]

    def __str__(self):
        return f"{self.student_id} / {self.topic_id}: {self.learning_level}"
