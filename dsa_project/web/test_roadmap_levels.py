"""Tests for the real mastery levels on the roadmap."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from attempts.factories import AttemptLog, make_catalogue
from attempts.tests import make_student

from .services import RoadmapService


class RoadmapLevelTests(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.student = make_student()
        self.log = AttemptLog(self.student)
        self.service = RoadmapService()

    def arrays(self, student=None):
        roadmap = self.service.get_roadmap(student or self.student)
        return next(item for item in roadmap if item.topic == self.c.arrays)

    def test_no_attempts_needs_three_more(self):
        item = self.arrays()
        self.assertEqual((item.level, item.mastery, item.attempts, item.attempts_needed), ("Not enough data", None, 0, 3))

    def test_two_attempts_need_one_more(self):
        self.log.many(self.c.easy1, "CC")
        item = self.arrays()
        self.assertEqual((item.level, item.attempts, item.attempts_needed), ("Not enough data", 2, 1))

    def test_three_good_attempts_give_advanced(self):
        self.log.many(self.c.easy1, "CCC", secs=100)
        item = self.arrays()
        self.assertEqual((item.level, item.mastery, item.attempts, item.attempts_needed), ("Advanced", 100, 3, 0))

    def test_failures_give_beginner(self):
        self.log.many(self.c.easy1, "FFF")
        self.assertEqual(self.arrays().level, "Beginner")

    def test_mixed_results_give_intermediate(self):
        self.log.add(self.c.easy1, True, secs=100)
        self.log.add(self.c.easy2, False, secs=100)
        self.log.add(self.c.tp_easy, True, secs=100)
        self.log.add(self.c.easy2, False, secs=100)
        item = self.arrays()
        self.assertEqual(item.level, "Intermediate")
        self.assertTrue(40 <= item.mastery <= 70)

    def test_topics_have_their_own_levels(self):
        self.log.many(self.c.easy1, "CCC", secs=100)
        roadmap = {item.topic.name: item.level for item in self.service.get_roadmap(self.student)}
        self.assertEqual(roadmap, {"Arrays": "Advanced", "Strings": "Not enough data", "Graphs": "Not enough data"})

    def test_other_students_attempts_do_not_count(self):
        AttemptLog(make_student("other@example.com")).many(self.c.easy1, "CCC", secs=100)
        self.assertEqual(self.arrays().level, "Not enough data")

    def test_solved_counts_per_subtopic(self):
        self.log.add(self.c.easy1, True)
        self.log.add(self.c.easy2, False)  # tried, not solved
        self.log.add(self.c.tp_easy, True)
        item = self.arrays()
        counts = {sub.subtopic.name: (sub.solved_count, sub.problem_count) for sub in item.subtopics}
        self.assertEqual(counts, {"Traversal": (1, 4), "Two Pointers": (1, 2)})

    def test_a_problem_solved_twice_counts_once(self):
        self.log.many(self.c.easy1, "CC")
        self.assertEqual(self.arrays().subtopics[0].solved_count, 1)


class RoadmapPageLevelTests(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student()
        self.client.force_login(self.student)

    def solve_three_arrays_problems(self):
        from problems.models import Problem

        log = AttemptLog(self.student)
        for title in ("Sum of Array", "Reverse an Array", "Second Largest Element"):
            log.add(Problem.objects.get(title=title), True, secs=60)

    def test_page_shows_the_level_and_the_score(self):
        self.solve_three_arrays_problems()
        response = self.client.get(reverse("roadmap"))
        self.assertContains(response, "Advanced")
        self.assertContains(response, "Mastery score 100 out of 100")
        self.assertContains(response, "3 attempts in this topic")

    def test_topics_without_data_say_what_is_missing(self):
        self.solve_three_arrays_problems()
        response = self.client.get(reverse("roadmap"))
        self.assertContains(response, "Not enough data yet", count=2)  # Strings and Searching and Sorting
        self.assertContains(response, "Needs 3 more attempts")

    def test_page_shows_solved_counts(self):
        self.solve_three_arrays_problems()
        response = self.client.get(reverse("roadmap"))
        self.assertContains(response, "2 of 2 solved")  # Traversal: Sum of Array and Second Largest Element
        self.assertContains(response, "1 of 2 solved")  # Two Pointers: Reverse an Array
