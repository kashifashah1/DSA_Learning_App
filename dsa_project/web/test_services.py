"""Unit tests for ProblemListService and RoadmapService (the logic behind the pages)."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from attempts.tests import make_attempt, make_student
from problems.models import Problem, Subtopic, Topic

from .services import ATTEMPTED, NOT_ATTEMPTED, SOLVED, ProblemListService, RoadmapService


class ProblemListFilterTests(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())  # 3 topics, 6 subtopics, 12 problems (5 Easy, 4 Medium, 3 Hard)
        self.student = make_student()
        self.service = ProblemListService()

    def titles(self, **filters):
        return [row.problem.title for row in self.service.get_problems(self.student, **filters)]

    def test_no_filter_returns_all_problems(self):
        self.assertEqual(len(self.titles()), 12)

    def test_filter_by_topic(self):
        arrays = Topic.objects.get(name="Arrays")
        rows = self.service.get_problems(self.student, topic=arrays)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row.problem.topic == arrays for row in rows))

    def test_filter_by_subtopic(self):
        subtopic = Subtopic.objects.get(name="Binary Search")
        self.assertEqual(sorted(self.titles(subtopic=subtopic)), ["Binary Search", "Search in Rotated Sorted Array"])

    def test_filter_by_difficulty(self):
        self.assertEqual(len(self.titles(difficulty="Easy")), 5)
        self.assertEqual(len(self.titles(difficulty="Medium")), 4)
        self.assertEqual(len(self.titles(difficulty="Hard")), 3)

    def test_filters_work_together(self):
        strings = Topic.objects.get(name="Strings")
        self.assertEqual(
            sorted(self.titles(topic=strings, difficulty="Easy")), ["Count Vowels", "Palindrome Check"]
        )

    def test_filter_with_no_match_gives_empty_list(self):
        arrays = Topic.objects.get(name="Arrays")
        self.assertEqual(self.titles(topic=arrays, difficulty="Hard"), [])

    def test_empty_values_mean_no_filter(self):
        self.assertEqual(len(self.titles(topic=None, subtopic=None, difficulty="")), 12)

    def test_problems_come_in_catalogue_order(self):
        topic_order = [row.problem.topic.order for row in self.service.get_problems(self.student)]
        self.assertEqual(topic_order, sorted(topic_order))


class ProblemStatusTests(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student()
        self.service = ProblemListService()
        self.sum_problem = Problem.objects.get(title="Sum of Array")
        self.palindrome = Problem.objects.get(title="Palindrome Check")

    def status_of(self, student, problem):
        for row in self.service.get_problems(student):
            if row.problem == problem:
                return row.status

    def test_everything_starts_as_not_attempted(self):
        rows = self.service.get_problems(self.student)
        self.assertTrue(all(row.status == NOT_ATTEMPTED for row in rows))

    def test_wrong_attempt_gives_attempted(self):
        make_attempt(self.student, self.sum_problem, is_correct=False)
        self.assertEqual(self.status_of(self.student, self.sum_problem), ATTEMPTED)
        self.assertEqual(self.status_of(self.student, self.palindrome), NOT_ATTEMPTED)

    def test_correct_attempt_gives_solved(self):
        make_attempt(self.student, self.sum_problem, is_correct=True)
        self.assertEqual(self.status_of(self.student, self.sum_problem), SOLVED)

    def test_solved_stays_solved_after_a_later_wrong_attempt(self):
        make_attempt(self.student, self.sum_problem, attempt_no=1, is_correct=True)
        make_attempt(self.student, self.sum_problem, attempt_no=2, is_correct=False)
        self.assertEqual(self.status_of(self.student, self.sum_problem), SOLVED)

    def test_status_belongs_to_the_logged_in_student_only(self):
        other = make_student("other@example.com")
        make_attempt(other, self.sum_problem, is_correct=True)
        self.assertEqual(self.status_of(self.student, self.sum_problem), NOT_ATTEMPTED)
        self.assertEqual(self.status_of(other, self.sum_problem), SOLVED)

    def test_list_status_agrees_with_the_problem_methods(self):
        make_attempt(self.student, self.sum_problem, is_correct=True)
        make_attempt(self.student, self.palindrome, is_correct=False)
        for row in self.service.get_problems(self.student):
            with self.subTest(problem=row.problem.title):
                if row.problem.is_solved_by(self.student):
                    self.assertEqual(row.status, SOLVED)
                elif row.problem.is_attempted_by(self.student):
                    self.assertEqual(row.status, ATTEMPTED)
                else:
                    self.assertEqual(row.status, NOT_ATTEMPTED)


class RoadmapServiceTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.service = RoadmapService()

    def test_empty_catalogue_gives_empty_roadmap(self):
        self.assertEqual(self.service.get_roadmap(self.student), [])

    def test_topics_and_subtopics_follow_their_order_numbers(self):
        # Created in the "wrong" order on purpose.
        strings = Topic.objects.create(name="Strings", order=2)
        arrays = Topic.objects.create(name="Arrays", order=1)
        Subtopic.objects.create(topic=arrays, name="Two Pointers", order=2)
        Subtopic.objects.create(topic=arrays, name="Traversal", order=1)
        Subtopic.objects.create(topic=strings, name="Basics", order=1)

        roadmap = self.service.get_roadmap(self.student)
        self.assertEqual([item.topic.name for item in roadmap], ["Arrays", "Strings"])
        self.assertEqual([s.subtopic.name for s in roadmap[0].subtopics], ["Traversal", "Two Pointers"])

    def test_a_student_without_attempts_has_no_level_anywhere(self):
        call_command("seed_problems", stdout=StringIO())
        for item in self.service.get_roadmap(self.student):
            self.assertEqual(item.level, "Not enough data")
            self.assertIsNone(item.mastery)
            self.assertEqual(item.attempts, 0)

    def test_problem_count_per_subtopic(self):
        call_command("seed_problems", stdout=StringIO())
        roadmap = self.service.get_roadmap(self.student)
        counts = [sub.problem_count for item in roadmap for sub in item.subtopics]
        self.assertEqual(counts, [2] * 6)
        self.assertEqual([sub.solved_count for item in roadmap for sub in item.subtopics], [0] * 6)

    def test_topic_without_subtopics_is_listed(self):
        Topic.objects.create(name="Graphs", order=1)
        roadmap = self.service.get_roadmap(self.student)
        self.assertEqual(roadmap[0].subtopics, [])
