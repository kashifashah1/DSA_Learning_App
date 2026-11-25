"""Trains the success model from the stored attempts. Run it yourself; it never runs inside a web request.

    python manage.py train_model
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.demo import demo_attempts
from analytics.ml import ModelTrainingError, SuccessPredictor
from analytics.services import PerformanceAnalyzer
from attempts.models import Attempt


class Command(BaseCommand):
    help = "Train Logistic Regression and Decision Tree on the stored attempts and save the better model."

    def handle(self, *args, **options):
        stored = Attempt.objects.count()
        minimum = settings.MIN_ATTEMPTS_FOR_MODEL
        if stored < minimum:
            raise CommandError(
                f"Not enough attempts to train a model: {stored} stored, at least {minimum} are needed "
                f"(MIN_ATTEMPTS_FOR_MODEL). Until then the system uses its rules only. Nothing was trained."
            )

        data = PerformanceAnalyzer().build_training_data()
        fake = demo_attempts().count()
        try:
            report = SuccessPredictor().train(
                data, notes={"contains_demo_data": fake > 0, "demo_rows": fake}
            )
        except ModelTrainingError as error:
            raise CommandError(f"Could not train the model: {error} Nothing was saved.")

        out = self.stdout.write
        out(self.style.SUCCESS("Model trained and saved."))
        out(f"  Attempts used:   {report.rows} ({report.solved_rows} solved, {report.rows - report.solved_rows} not solved)")
        out(f"  Train / test:    {report.train_rows} / {report.test_rows} attempts")
        out("  Test results (on attempts the models did not see):")
        for score in report.scores:
            out(f"    {score.name:<20} accuracy {score.accuracy:.3f}   F1 {score.f1:.3f}")
        out(f"  Kept:            {report.chosen}")
        out(f"  Saved to:        {report.path}")
        if fake:
            out(self.style.WARNING(
                f"  WARNING: {fake} of the {report.rows} attempts are FAKE demo data. "
                f"Do not present this model or its numbers as real."
            ))
