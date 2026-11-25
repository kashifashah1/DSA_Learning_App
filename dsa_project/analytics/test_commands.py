"""Tests for the commands generate_demo_attempts and train_model (Step 9)."""

import shutil
import tempfile
from io import StringIO
from pathlib import Path

import joblib
from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from attempts.factories import AttemptLog, make_catalogue
from attempts.models import Attempt
from attempts.tests import make_student
from users.models import User

from . import ml
from .demo import DEMO_DOMAIN, DEMO_SOURCE_CODE, demo_attempts, demo_students


def run(command, *args, **options):
    out = StringIO()
    call_command(command, *args, stdout=out, **options)
    return out.getvalue()


class CommandTestBase(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        folder = Path(tempfile.mkdtemp(prefix="dsa_cmd_test_"))
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.model_path = folder / "success_model.joblib"
        override = override_settings(MODEL_PATH=self.model_path, DEBUG=True)
        override.enable()
        self.addCleanup(override.disable)
        ml._MODEL_CACHE.clear()
        self.addCleanup(ml._MODEL_CACHE.clear)

    def demo(self, students=10, attempts=15, **options):
        return run("generate_demo_attempts", students=students, attempts_per_student=attempts, **options)


class GenerateDemoAttemptsTests(CommandTestBase):
    def test_refuses_to_run_outside_development(self):
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError) as caught:
                self.demo()
        self.assertIn("development only", str(caught.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_creates_the_students_and_attempts(self):
        output = self.demo(students=6, attempts=10)
        self.assertEqual(demo_students().count(), 6)
        self.assertEqual(demo_attempts().count(), 60)
        self.assertIn("6 FAKE students", output)
        self.assertIn("60 FAKE attempts", output)

    def test_everything_is_clearly_labelled_as_fake(self):
        output = self.demo(students=5)
        self.assertIn("FAKE", output)
        self.assertIn("never present it as real", output.lower())
        for student in demo_students():
            self.assertTrue(student.email.endswith("@" + DEMO_DOMAIN))
            self.assertEqual(DEMO_DOMAIN, "demo.invalid")  # such addresses cannot exist
            self.assertTrue(student.name.startswith("DEMO "))
            self.assertTrue(student.name.endswith("(fake)"))
        self.assertEqual(set(demo_attempts().values_list("source_code", flat=True)), {DEMO_SOURCE_CODE})
        self.assertIn("DEMO DATA", DEMO_SOURCE_CODE)

    def test_nobody_can_log_in_as_a_demo_student(self):
        self.demo(students=2)
        student = demo_students().first()
        self.assertFalse(student.has_usable_password())
        for password in ("", "password", student.email, "DEMO"):
            self.assertFalse(self.client.login(username=student.email, password=password))

    def test_the_attempts_are_valid(self):
        self.demo(students=5, attempts=20)
        seen = set()
        for attempt in demo_attempts():
            key = (attempt.student_id, attempt.problem_id, attempt.attempt_no)
            self.assertNotIn(key, seen)
            seen.add(key)
            self.assertLessEqual(attempt.tests_passed, attempt.tests_total)
            self.assertEqual(attempt.difficulty, attempt.problem.difficulty)
            self.assertGreater(attempt.time_taken_sec, 0)
        for student in demo_students():  # attempt numbers go 1, 2, 3 for every problem
            for problem_id in {a.problem_id for a in student.attempts.all()}:
                numbers = sorted(student.attempts.filter(problem_id=problem_id).values_list("attempt_no", flat=True))
                self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_attempt_times_are_in_the_past(self):
        from django.utils import timezone

        self.demo(students=5)
        self.assertLessEqual(max(a.submitted_at for a in demo_attempts()), timezone.now())

    def test_the_same_seed_gives_the_same_data(self):
        def snapshot():
            return [
                (a.student.email, a.problem_id, a.is_correct, a.time_taken_sec, a.attempt_no)
                for a in demo_attempts().order_by("student__email", "problem_id", "attempt_no")
            ]

        self.demo(seed=7)
        first = snapshot()
        run("generate_demo_attempts", clear=True)
        self.demo(seed=7)
        self.assertEqual(snapshot(), first)
        run("generate_demo_attempts", clear=True)
        self.demo(seed=8)
        self.assertNotEqual(snapshot(), first)

    def test_it_refuses_to_add_a_second_set_without_clear(self):
        self.demo(students=3)
        with self.assertRaises(CommandError) as caught:
            self.demo(students=3)
        self.assertIn("--clear", str(caught.exception))
        self.assertEqual(demo_students().count(), 3)

    def test_clear_removes_only_the_fake_data(self):
        real = make_student("real@example.com")
        AttemptLog(real).many(self.c.easy1, "CFC")
        self.demo(students=4)
        output = run("generate_demo_attempts", clear=True)
        self.assertIn("Removed 4 fake student", output)
        self.assertEqual(demo_students().count(), 0)
        self.assertEqual(demo_attempts().count(), 0)
        self.assertEqual(User.objects.filter(email="real@example.com").count(), 1)
        self.assertEqual(Attempt.objects.for_student(real).count(), 3)  # the real attempts are untouched

    def test_clear_also_needs_development_mode(self):
        self.demo(students=2)
        with override_settings(DEBUG=False):
            with self.assertRaises(CommandError):
                run("generate_demo_attempts", clear=True)
        self.assertEqual(demo_students().count(), 2)

    def test_real_students_are_never_created_or_changed(self):
        real = make_student("real@example.com")
        self.demo(students=3)
        self.assertEqual(User.objects.exclude(email__endswith="@" + DEMO_DOMAIN).count(), 1)
        real.refresh_from_db()
        self.assertTrue(real.has_usable_password())

    def test_it_needs_problems(self):
        from problems.models import Problem

        Problem.objects.all().delete()
        with self.assertRaises(CommandError) as caught:
            self.demo()
        self.assertIn("seed_problems", str(caught.exception))
        self.assertEqual(User.objects.count(), 0)  # nothing half-made

    def test_wrong_numbers_are_refused(self):
        with self.assertRaises(CommandError):
            self.demo(students=0)
        with self.assertRaises(CommandError):
            self.demo(attempts=0)


class TrainModelCommandTests(CommandTestBase):
    def test_refuses_when_there_are_fewer_attempts_than_the_minimum(self):
        self.demo(students=6, attempts=15)  # 90 attempts: below the minimum of 100
        with self.assertRaises(CommandError) as caught:
            run("train_model")
        message = str(caught.exception)
        self.assertIn("Not enough attempts", message)
        self.assertIn("90 stored", message)
        self.assertIn("at least 100", message)
        self.assertIn("rules only", message)
        self.assertFalse(self.model_path.exists())  # nothing was trained or saved

    def test_refuses_with_no_attempts_at_all(self):
        with self.assertRaises(CommandError):
            run("train_model")
        self.assertFalse(self.model_path.exists())

    def test_the_boundary_is_exactly_the_minimum(self):
        self.demo(students=6, attempts=15)  # 90 attempts
        with override_settings(MIN_ATTEMPTS_FOR_MODEL=91):
            with self.assertRaises(CommandError):
                run("train_model")
        with override_settings(MIN_ATTEMPTS_FOR_MODEL=90):
            self.assertIn("Model trained and saved", run("train_model"))

    def test_trains_saves_and_prints_a_short_report(self):
        self.demo(students=10, attempts=15)  # 150 attempts
        output = run("train_model")
        self.assertTrue(self.model_path.exists())
        for text in ("Model trained and saved", "Attempts used:   150", "Train / test:", ml.LOGISTIC, ml.TREE,
                     "accuracy", "F1", "Kept:", str(self.model_path)):
            self.assertIn(text, output)
        self.assertIn("Test results (on attempts the models did not see)", output)

    def test_the_report_warns_when_fake_data_was_used(self):
        self.demo(students=10, attempts=15)
        output = run("train_model")
        self.assertIn("FAKE demo data", output)
        self.assertIn("150 of the 150", output)
        notes = joblib.load(self.model_path)["notes"]
        self.assertEqual(notes, {"contains_demo_data": True, "demo_rows": 150})

    def test_no_warning_when_only_real_attempts_are_used(self):
        for number in range(8):
            AttemptLog(make_student(f"s{number}@example.com")).many(self.c.easy1, "CFCCFFCCFCFCFCFCFC"[:16])
        self.assertGreaterEqual(Attempt.objects.count(), 100)
        output = run("train_model")
        self.assertNotIn("FAKE", output)
        self.assertEqual(joblib.load(self.model_path)["notes"], {"contains_demo_data": False, "demo_rows": 0})

    def test_refuses_when_all_attempts_have_the_same_outcome(self):
        for number in range(10):
            AttemptLog(make_student(f"s{number}@example.com")).many(self.c.easy1, "CCCCCCCCCCCC")  # all correct
        with self.assertRaises(CommandError) as caught:
            run("train_model")
        self.assertIn("both solved and not-solved", str(caught.exception))
        self.assertIn("Nothing was saved", str(caught.exception))
        self.assertFalse(self.model_path.exists())

    def test_retraining_replaces_the_model(self):
        self.demo(students=10, attempts=15)
        run("train_model")
        first = self.model_path.stat().st_mtime_ns
        run("train_model")
        self.assertGreaterEqual(self.model_path.stat().st_mtime_ns, first)
        self.assertEqual([p.name for p in self.model_path.parent.iterdir()], ["success_model.joblib"])

    def test_the_trained_model_is_then_available(self):
        self.demo(students=10, attempts=15)
        run("train_model")
        self.assertTrue(ml.SuccessPredictor().is_available())  # file loads and 150 >= 100 attempts


class TrainingNeverHappensOnTheWebTests(TestCase):
    """The model is trained only by `python manage.py train_model`, never inside a web request."""

    def test_no_web_code_can_start_training(self):
        for folder in ("web", "recommendations", "users", "problems", "attempts"):
            for path in (Path(settings.BASE_DIR) / folder).glob("*.py"):
                if path.name.startswith("test"):
                    continue
                text = path.read_text()
                self.assertNotIn(".train(", text, path.name)
                self.assertNotIn("train_model", text, path.name)
                self.assertNotIn("build_training_data", text, path.name)

    def test_templates_never_mention_training(self):
        for path in (Path(settings.BASE_DIR) / "templates").rglob("*.html"):
            self.assertNotIn("train_model", path.read_text(), path.name)

    def test_only_the_management_command_calls_train(self):
        callers = []
        for path in (Path(settings.BASE_DIR) / "analytics").rglob("*.py"):
            if path.name.startswith("test"):
                continue
            if ".train(" in path.read_text():
                callers.append(path.name)
        self.assertEqual(callers, ["train_model.py"])
