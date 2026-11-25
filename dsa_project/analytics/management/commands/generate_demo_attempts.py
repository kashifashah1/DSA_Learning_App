"""DEVELOPMENT ONLY. Makes FAKE students and attempts so that `train_model` can be tried out.

    python manage.py generate_demo_attempts                 # 40 fake students, 15 attempts each
    python manage.py generate_demo_attempts --clear         # remove all fake students and their attempts

The data is made up. It must never be shown or described as real data.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.demo import clear_demo_data, demo_students, generate_demo_data


class Command(BaseCommand):
    help = "DEVELOPMENT ONLY: create clearly labelled FAKE students and attempts for testing the model."

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=40, help="number of fake students (default 40)")
        parser.add_argument("--attempts-per-student", type=int, default=15, help="attempts for each (default 15)")
        parser.add_argument("--seed", type=int, default=42, help="same seed = same fake data (default 42)")
        parser.add_argument("--clear", action="store_true", help="delete the fake students and attempts, then stop")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("generate_demo_attempts is for development only (it needs DEBUG=True).")
        if options["students"] < 1 or options["attempts_per_student"] < 1:
            raise CommandError("--students and --attempts-per-student must be at least 1.")

        self.stdout.write(self.style.WARNING(
            "DEVELOPMENT ONLY: this data is FAKE. Never present it as real student data."
        ))

        if options["clear"]:
            removed = clear_demo_data()
            self.stdout.write(self.style.SUCCESS(f"Removed {removed} fake student(s) and all their attempts."))
            return

        if demo_students().exists():
            raise CommandError(
                "Fake demo students already exist. Run with --clear first to remove them."
            )
        try:
            students, attempts = generate_demo_data(
                students=options["students"],
                attempts_per_student=options["attempts_per_student"],
                seed=options["seed"],
            )
        except ValueError as error:
            raise CommandError(str(error))
        self.stdout.write(self.style.SUCCESS(
            f"Created {students} FAKE students (demo-student-NNN@demo.invalid) with {attempts} FAKE attempts."
        ))
        self.stdout.write("Next: python manage.py train_model   (remove the fake data later with --clear)")
