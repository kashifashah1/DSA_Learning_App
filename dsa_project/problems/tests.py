"""Tests for Step 2: model constraints, admin pages and the seed command."""

from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import reverse

from users.models import User

from .models import Problem, Subtopic, Topic
from .models import TestCase as ProblemTestCase  # avoid a clash with django.test.TestCase


def make_catalogue():
    """One topic -> one subtopic -> one problem with two test cases."""
    topic = Topic.objects.create(name="Arrays", order=1)
    subtopic = Subtopic.objects.create(topic=topic, name="Traversal", order=1)
    problem = Problem.objects.create(
        title="Sum", statement="Print the sum.", difficulty="Easy", subtopic=subtopic
    )
    ProblemTestCase.objects.create(problem=problem, input_data="1\n2", expected_output="2", is_sample=True)
    ProblemTestCase.objects.create(problem=problem, input_data="2\n1 2", expected_output="3")
    return topic, subtopic, problem


class TopicTests(TestCase):
    def test_name_must_be_unique(self):
        Topic.objects.create(name="Arrays")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Topic.objects.create(name="Arrays")

    def test_topics_are_listed_by_order(self):
        Topic.objects.create(name="Strings", order=2)
        Topic.objects.create(name="Arrays", order=1)
        self.assertEqual([t.name for t in Topic.objects.all()], ["Arrays", "Strings"])

    def test_cannot_delete_topic_that_has_subtopics(self):
        topic, _, _ = make_catalogue()
        with self.assertRaises(ProtectedError):
            topic.delete()


class SubtopicTests(TestCase):
    def test_name_is_unique_inside_one_topic(self):
        topic = Topic.objects.create(name="Arrays")
        Subtopic.objects.create(topic=topic, name="Basics")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subtopic.objects.create(topic=topic, name="Basics")

    def test_same_name_is_allowed_in_another_topic(self):
        arrays = Topic.objects.create(name="Arrays")
        strings = Topic.objects.create(name="Strings")
        Subtopic.objects.create(topic=arrays, name="Basics")
        Subtopic.objects.create(topic=strings, name="Basics")
        self.assertEqual(Subtopic.objects.filter(name="Basics").count(), 2)

    def test_subtopic_needs_a_topic(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Subtopic.objects.create(name="Lonely")

    def test_cannot_delete_subtopic_that_has_problems(self):
        _, subtopic, _ = make_catalogue()
        with self.assertRaises(ProtectedError):
            subtopic.delete()


class ProblemTests(TestCase):
    def test_topic_is_reached_through_subtopic(self):
        topic, _, problem = make_catalogue()
        self.assertEqual(problem.topic, topic)

    def test_created_at_is_filled_automatically(self):
        _, _, problem = make_catalogue()
        self.assertIsNotNone(problem.created_at)

    def test_difficulty_must_be_easy_medium_or_hard(self):
        _, subtopic, _ = make_catalogue()
        for good in ["Easy", "Medium", "Hard"]:
            Problem(title="P", statement="S", difficulty=good, subtopic=subtopic).full_clean()
        with self.assertRaises(ValidationError):
            Problem(title="P", statement="S", difficulty="Impossible", subtopic=subtopic).full_clean()

    def test_title_and_statement_are_required(self):
        _, subtopic, _ = make_catalogue()
        with self.assertRaises(ValidationError) as caught:
            Problem(title="", statement="", difficulty="Easy", subtopic=subtopic).full_clean()
        self.assertIn("title", caught.exception.message_dict)
        self.assertIn("statement", caught.exception.message_dict)

    def test_problem_needs_a_subtopic(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Problem.objects.create(title="P", statement="S", difficulty="Easy")


class TestCaseModelTests(TestCase):
    def test_sample_flag_defaults_to_false(self):
        _, _, problem = make_catalogue()
        case = ProblemTestCase.objects.create(problem=problem, input_data="1", expected_output="1")
        self.assertFalse(case.is_sample)

    def test_test_cases_are_deleted_with_their_problem(self):
        _, _, problem = make_catalogue()
        self.assertEqual(ProblemTestCase.objects.count(), 2)
        problem.delete()
        self.assertEqual(ProblemTestCase.objects.count(), 0)

    def test_problem_lists_its_test_cases(self):
        _, _, problem = make_catalogue()
        self.assertEqual(problem.test_cases.count(), 2)
        self.assertEqual(problem.test_cases.filter(is_sample=True).count(), 1)

    def test_test_case_needs_a_problem(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProblemTestCase.objects.create(input_data="1", expected_output="1")


class AdminTests(TestCase):
    """The administrator manages the catalogue in the Django admin (staff only)."""

    def setUp(self):
        self.staff = User.objects.create_user(
            email="admin@example.com", name="Admin", password="Strong#Pass123", is_staff=True
        )
        self.student = User.objects.create_user(
            email="student@example.com", name="Student", password="Strong#Pass123"
        )
        self.topic, self.subtopic, self.problem = make_catalogue()

    def test_all_four_models_are_registered(self):
        self.client.force_login(self.staff)
        for model in ["topic", "subtopic", "problem", "testcase"]:
            with self.subTest(model=model):
                self.assertEqual(self.client.get(reverse(f"admin:problems_{model}_changelist")).status_code, 200)
                self.assertEqual(self.client.get(reverse(f"admin:problems_{model}_add")).status_code, 200)

    def test_students_cannot_open_the_admin_pages(self):
        self.client.force_login(self.student)
        for model in ["topic", "subtopic", "problem", "testcase"]:
            with self.subTest(model=model):
                response = self.client.get(reverse(f"admin:problems_{model}_changelist"))
                self.assertEqual(response.status_code, 302)
                self.assertIn("/admin/login/", response.url)

    def test_test_cases_show_inside_the_problem_page(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin:problems_problem_change", args=[self.problem.pk]))
        self.assertContains(response, "test_cases-0-input_data")
        self.assertContains(response, "test_cases-1-expected_output")

    def test_admin_can_add_a_problem_with_test_cases(self):
        self.client.force_login(self.staff)
        data = {
            "title": "Product of Array",
            "statement": "Print the product.",
            "difficulty": "Medium",
            "subtopic": self.subtopic.pk,
            "test_cases-TOTAL_FORMS": "2",
            "test_cases-INITIAL_FORMS": "0",
            "test_cases-MIN_NUM_FORMS": "0",
            "test_cases-MAX_NUM_FORMS": "1000",
            "test_cases-0-input_data": "2\n2 3",
            "test_cases-0-expected_output": "6",
            "test_cases-0-is_sample": "on",
            "test_cases-1-input_data": "1\n5",
            "test_cases-1-expected_output": "5",
        }
        response = self.client.post(reverse("admin:problems_problem_add"), data)
        self.assertEqual(response.status_code, 302)
        problem = Problem.objects.get(title="Product of Array")
        self.assertEqual(problem.test_cases.count(), 2)
        self.assertEqual(problem.test_cases.filter(is_sample=True).count(), 1)

    def test_admin_can_edit_a_problem(self):
        self.client.force_login(self.staff)
        case_ids = list(self.problem.test_cases.values_list("id", flat=True))
        data = {
            "title": "Sum of Numbers",
            "statement": self.problem.statement,
            "difficulty": "Hard",
            "subtopic": self.subtopic.pk,
            "test_cases-TOTAL_FORMS": "2",
            "test_cases-INITIAL_FORMS": "2",
            "test_cases-MIN_NUM_FORMS": "0",
            "test_cases-MAX_NUM_FORMS": "1000",
            "test_cases-0-id": case_ids[0],
            "test_cases-0-problem": self.problem.pk,
            "test_cases-0-input_data": "1\n2",
            "test_cases-0-expected_output": "2",
            "test_cases-0-is_sample": "on",
            "test_cases-1-id": case_ids[1],
            "test_cases-1-problem": self.problem.pk,
            "test_cases-1-input_data": "2\n1 2",
            "test_cases-1-expected_output": "3",
        }
        response = self.client.post(reverse("admin:problems_problem_change", args=[self.problem.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.problem.refresh_from_db()
        self.assertEqual(self.problem.title, "Sum of Numbers")
        self.assertEqual(self.problem.difficulty, "Hard")

    def test_admin_can_delete_a_problem_with_its_test_cases(self):
        self.client.force_login(self.staff)
        url = reverse("admin:problems_problem_delete", args=[self.problem.pk])
        response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Problem.objects.count(), 0)
        self.assertEqual(ProblemTestCase.objects.count(), 0)

    def test_admin_rejects_a_wrong_difficulty(self):
        self.client.force_login(self.staff)
        data = {
            "title": "X", "statement": "Y", "difficulty": "Impossible", "subtopic": self.subtopic.pk,
            "test_cases-TOTAL_FORMS": "0", "test_cases-INITIAL_FORMS": "0",
            "test_cases-MIN_NUM_FORMS": "0", "test_cases-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("admin:problems_problem_add"), data)
        self.assertEqual(response.status_code, 200)  # form shown again with an error
        self.assertFalse(Problem.objects.filter(title="X").exists())


# ---------------------------------------------------------------------------
# Reference solutions: simple, trusted Python code used only to check that the
# expected outputs in the seed data are right. (The real code runner comes in Step 3.)
# ---------------------------------------------------------------------------
def _numbers(text):
    return [int(x) for x in text.split()]


def _sum(text):
    return str(sum(_numbers(text)[1:]))


def _second_largest(text):
    return str(sorted(set(_numbers(text)[1:]))[-2])


def _reverse_array(text):
    return " ".join(str(x) for x in reversed(_numbers(text)[1:]))


def _pair_sum(text):
    lines = text.split("\n")
    values, target = _numbers(lines[1]), int(lines[2])
    return "YES" if any(values[i] + values[j] == target for i in range(len(values)) for j in range(i + 1, len(values))) else "NO"


def _palindrome(text):
    return "YES" if text == text[::-1] else "NO"


def _reverse_words(text):
    return " ".join(reversed(text.split()))


def _vowels(text):
    return str(sum(1 for ch in text if ch in "aeiou"))


def _longest_unique(text):
    best, start, last_seen = 0, 0, {}
    for i, ch in enumerate(text):
        if ch in last_seen and last_seen[ch] >= start:
            start = last_seen[ch] + 1
        last_seen[ch] = i
        best = max(best, i - start + 1)
    return str(best)


def _find_index(text):
    lines = text.split("\n")
    values, target = _numbers(lines[1]), int(lines[2])
    return str(values.index(target)) if target in values else "-1"


def _merge(text):
    lines = text.split("\n")
    return " ".join(str(x) for x in sorted(_numbers(lines[1]) + _numbers(lines[3])))


def _inversions(text):
    values = _numbers(text)[1:]
    return str(sum(1 for i in range(len(values)) for j in range(i + 1, len(values)) if values[i] > values[j]))


REFERENCE_SOLUTIONS = {
    "Sum of Array": _sum,
    "Second Largest Element": _second_largest,
    "Reverse an Array": _reverse_array,
    "Pair With Given Sum": _pair_sum,
    "Palindrome Check": _palindrome,
    "Reverse Words in a Sentence": _reverse_words,
    "Count Vowels": _vowels,
    "Longest Substring Without Repeating Characters": _longest_unique,
    "Binary Search": _find_index,
    "Search in Rotated Sorted Array": _find_index,
    "Merge Two Sorted Arrays": _merge,
    "Count Inversions": _inversions,
}


class SeedCommandTests(TestCase):
    def run_seed(self):
        out = StringIO()
        call_command("seed_problems", stdout=out)
        return out.getvalue()

    def test_creates_the_sample_catalogue(self):
        output = self.run_seed()
        self.assertEqual(Topic.objects.count(), 3)
        self.assertEqual(Subtopic.objects.count(), 6)
        self.assertEqual(Problem.objects.count(), 12)
        self.assertIn("Created", output)
        for topic in Topic.objects.all():
            self.assertEqual(topic.subtopics.count(), 2)

    def test_each_problem_has_three_to_five_test_cases(self):
        self.run_seed()
        for problem in Problem.objects.all():
            with self.subTest(problem=problem.title):
                self.assertTrue(3 <= problem.test_cases.count() <= 5)

    def test_each_problem_has_a_sample_and_a_hidden_test_case(self):
        self.run_seed()
        for problem in Problem.objects.all():
            with self.subTest(problem=problem.title):
                self.assertTrue(problem.test_cases.filter(is_sample=True).exists())
                self.assertTrue(problem.test_cases.filter(is_sample=False).exists())

    def test_difficulties_are_mixed(self):
        self.run_seed()
        difficulties = set(Problem.objects.values_list("difficulty", flat=True))
        self.assertEqual(difficulties, {"Easy", "Medium", "Hard"})

    def test_every_statement_describes_input_and_output(self):
        self.run_seed()
        for problem in Problem.objects.all():
            with self.subTest(problem=problem.title):
                self.assertIn("Input:", problem.statement)
                self.assertIn("Output:", problem.statement)

    def test_running_twice_does_not_make_duplicates(self):
        self.run_seed()
        output = self.run_seed()
        self.assertEqual(Problem.objects.count(), 12)
        self.assertEqual(ProblemTestCase.objects.count(), 56)
        self.assertIn("Skipped 12", output)

    def test_running_again_keeps_admin_edits(self):
        self.run_seed()
        problem = Problem.objects.get(title="Sum of Array")
        problem.statement = "Edited by the administrator."
        problem.save()
        self.run_seed()
        problem.refresh_from_db()
        self.assertEqual(problem.statement, "Edited by the administrator.")

    def test_expected_outputs_match_the_reference_solutions(self):
        """Guards against typing mistakes in the seed data."""
        self.run_seed()
        self.assertEqual(set(REFERENCE_SOLUTIONS), set(Problem.objects.values_list("title", flat=True)))
        for case in ProblemTestCase.objects.select_related("problem"):
            with self.subTest(problem=case.problem.title, input=case.input_data):
                solve = REFERENCE_SOLUTIONS[case.problem.title]
                self.assertEqual(solve(case.input_data), case.expected_output)
