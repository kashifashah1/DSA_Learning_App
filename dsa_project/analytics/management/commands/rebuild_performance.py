"""Rebuild the stored topic performance rows from the attempts.

    python manage.py rebuild_performance

Normally not needed: the row of a topic is updated after every attempt. Use it once after
upgrading from an older version, or after importing attempts directly into the database.
"""

from django.core.management.base import BaseCommand

from analytics.services import PerformanceAnalyzer
from attempts.models import Attempt
from users.models import User


class Command(BaseCommand):
    help = "Rebuild the stored topic performance (mastery) rows of every student from the attempts."

    def handle(self, *args, **options):
        analyzer = PerformanceAnalyzer()
        student_ids = Attempt.objects.values_list("student_id", flat=True).distinct()
        rows = 0
        for student in User.objects.filter(pk__in=student_ids):
            rows += len(analyzer.sync_student(student))
        self.stdout.write(self.style.SUCCESS(f"Rebuilt {rows} topic performance row(s)."))
