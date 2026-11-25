"""Tests for the statistics and mastery code (analytics/services.py)."""

from datetime import timedelta

from django.test import TestCase, override_settings

from attempts.factories import NOW, AttemptLog, make_catalogue
from attempts.models import Attempt
from attempts.tests import make_student

from .services import NOT_ENOUGH_DATA, MasteryCalculator, PerformanceAnalyzer, TopicStats


class StatsTestBase(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.student = make_student()
        self.log = AttemptLog(self.student)
        self.analyzer = PerformanceAnalyzer()

    def stats(self, topic=None):
        return self.analyzer.topic_stats(self.student, topic or self.c.arrays)


class TopicStatsTests(StatsTestBase):
    def test_no_attempts_gives_nothing(self):
        self.assertIsNone(self.stats())
        self.assertEqual(self.analyzer.all_topic_stats(self.student), {})
        self.assertIsNone(self.analyzer.latest_attempt(self.student))

    def test_counts_and_accuracy(self):
        self.log.many(self.c.easy1, "CFCC")
        stats = self.stats()
        self.assertEqual((stats.total_attempts, stats.correct_attempts), (4, 3))
        self.assertEqual(stats.accuracy, 0.75)
        self.assertEqual(stats.recent_accuracy, 0.75)  # all 4 attempts fit in the recent window
        self.assertIsNone(stats.baseline_accuracy)

    def test_recent_accuracy_uses_only_the_last_window(self):
        self.log.many(self.c.easy1, "CCC")  # older
        self.log.many(self.c.easy2, "FFCCC")  # the last RECENT_WINDOW (5)
        stats = self.stats()
        self.assertEqual(stats.total_attempts, 8)
        self.assertEqual(stats.accuracy, 6 / 8)
        self.assertEqual(stats.recent_accuracy, 0.6)
        self.assertEqual(stats.baseline_accuracy, 1.0)  # the 3 older attempts

    def test_baseline_needs_enough_older_attempts(self):
        self.log.many(self.c.easy1, "CCFFCC")  # only 1 attempt older than the window of 5
        self.assertIsNone(self.stats().baseline_accuracy)

    @override_settings(RECENT_WINDOW=2)
    def test_window_size_comes_from_settings(self):
        self.log.many(self.c.easy1, "CCCCFF")
        stats = self.stats()
        self.assertEqual(stats.recent_accuracy, 0.0)
        self.assertEqual(stats.baseline_accuracy, 1.0)

    def test_average_time_and_attempts_per_problem(self):
        self.log.many(self.c.easy1, "FFC", secs=100)  # 3 attempts on one problem
        self.log.add(self.c.easy2, True, secs=200)  # 1 attempt on another
        stats = self.stats()
        self.assertEqual(stats.avg_time_sec, (100 * 3 + 200) / 4)
        self.assertEqual(stats.avg_attempts, 2.0)  # 4 attempts on 2 problems

    def test_speed_compares_with_the_expected_time(self):
        self.log.add(self.c.easy1, True, secs=150)  # expected 300 for Easy: fast enough, 1.0
        self.log.add(self.c.easy2, True, secs=600)  # twice as slow: 0.5
        self.log.add(self.c.medium, False, secs=9999)  # failed attempts are ignored
        self.assertEqual(self.stats().speed_score, 0.75)

    def test_speed_is_zero_without_a_correct_attempt_and_capped_at_one(self):
        self.log.add(self.c.easy1, False)
        self.assertEqual(self.stats().speed_score, 0.0)
        self.log.add(self.c.easy2, True, secs=0)  # unknown time must not divide by zero
        self.assertEqual(self.stats().speed_score, 1.0)

    def test_efficiency_rewards_solving_on_the_first_try(self):
        self.log.add(self.c.easy1, True)  # solved on try 1 -> 1
        self.log.many(self.c.easy2, "FFC")  # solved on try 3 -> 1/3
        self.log.add(self.c.medium, False)  # never solved: not counted
        self.assertAlmostEqual(self.stats().efficiency_score, (1 + 1 / 3) / 2)

    def test_efficiency_is_zero_when_nothing_is_solved(self):
        self.log.many(self.c.easy1, "FF")
        self.assertEqual(self.stats().efficiency_score, 0.0)

    def test_last_practised_is_the_newest_attempt(self):
        self.log.at(days_ago=10).add(self.c.easy1, True)
        newest = self.log.at(days_ago=2).add(self.c.easy2, False)
        self.assertEqual(self.stats().last_practised, newest.submitted_at)

    def test_topics_are_kept_apart(self):
        self.log.many(self.c.easy1, "CC")
        self.log.many(self.c.s_easy, "F")
        everything = self.analyzer.all_topic_stats(self.student)
        self.assertEqual(set(everything), {self.c.arrays.pk, self.c.strings.pk})
        self.assertEqual(everything[self.c.arrays.pk].accuracy, 1.0)
        self.assertEqual(everything[self.c.strings.pk].accuracy, 0.0)
        self.assertEqual(self.stats(self.c.arrays).total_attempts, 2)
        self.assertIsNone(self.stats(self.c.graphs))

    def test_only_the_students_own_attempts_count(self):
        other = make_student("other@example.com")
        AttemptLog(other).many(self.c.easy1, "FFFF")
        self.log.many(self.c.easy1, "C")
        self.assertEqual(self.stats().total_attempts, 1)
        self.assertEqual(self.analyzer.topic_stats(other, self.c.arrays).total_attempts, 4)

    def test_same_data_gives_the_same_numbers_whatever_the_insert_order(self):
        """Determinism: the order in which rows were inserted must not change the result."""
        # (problem, attempt number, correct, seconds, minutes after the start)
        rows = [
            (self.c.easy1, 1, True, 100, 0), (self.c.easy1, 2, False, 200, 10),
            (self.c.easy2, 1, True, 300, 20), (self.c.medium, 1, False, 400, 30),
            (self.c.medium, 2, True, 500, 40),
        ]
        twin = make_student("twin@example.com")

        def insert(student, ordered_rows):
            for problem, number, correct, secs, minutes in ordered_rows:
                Attempt.objects.create(
                    student=student, problem=problem, source_code="x", difficulty=problem.difficulty,
                    is_correct=correct, tests_passed=1, tests_total=1, attempt_no=number, time_taken_sec=secs,
                    submitted_at=NOW - timedelta(hours=2) + timedelta(minutes=minutes),
                )

        insert(self.student, rows)
        insert(twin, list(reversed(rows)))
        self.assertEqual(self.stats(), self.analyzer.topic_stats(twin, self.c.arrays))

    def test_calling_twice_gives_the_same_result(self):
        self.log.many(self.c.easy1, "CFCFC")
        self.assertEqual(self.stats(), self.stats())


class RecentAndSubtopicTests(StatsTestBase):
    def test_recent_attempts_are_the_last_five_newest_first(self):
        attempts = self.log.many(self.c.easy1, "CCCCCCC")
        recent = self.analyzer.recent_attempts(self.student, self.c.arrays)
        self.assertEqual([a.pk for a in recent], [a.pk for a in reversed(attempts[-5:])])

    def test_latest_attempt_is_the_newest_in_any_topic(self):
        self.log.add(self.c.easy1, True)
        newest = self.log.add(self.c.s_easy, False)
        self.assertEqual(self.analyzer.latest_attempt(self.student), newest)

    def test_subtopic_accuracy_in_roadmap_order(self):
        self.log.many(self.c.tp_easy, "CF")  # Two Pointers (order 2)
        self.log.many(self.c.easy1, "CCC")  # Traversal (order 1)
        rows = self.analyzer.subtopic_accuracy(self.student, self.c.arrays)
        self.assertEqual([r.subtopic.name for r in rows], ["Traversal", "Two Pointers"])
        self.assertEqual([r.attempts for r in rows], [3, 2])
        self.assertEqual([r.accuracy for r in rows], [1.0, 0.5])

    def test_subtopics_without_attempts_are_not_listed(self):
        self.log.add(self.c.easy1, True)
        self.assertEqual(len(self.analyzer.subtopic_accuracy(self.student, self.c.arrays)), 1)


def fake_stats(**values):
    base = dict(topic=None, total_attempts=10, correct_attempts=8, accuracy=0.8, recent_accuracy=0.6,
                baseline_accuracy=None, avg_time_sec=0, avg_attempts=1, speed_score=0.5,
                efficiency_score=1.0, last_practised=NOW)
    base.update(values)
    return TopicStats(**base)


class MasteryTests(TestCase):
    def setUp(self):
        self.mastery = MasteryCalculator()

    def test_formula_uses_the_weights(self):
        # 100 * (0.5 * 0.8 + 0.2 * 0.6 + 0.15 * 0.5 + 0.15 * 1.0) = 74.5
        self.assertEqual(self.mastery.mastery_score(fake_stats()), 74.5)

    def test_perfect_and_zero(self):
        perfect = fake_stats(accuracy=1, recent_accuracy=1, speed_score=1, efficiency_score=1)
        zero = fake_stats(accuracy=0, recent_accuracy=0, speed_score=0, efficiency_score=0)
        self.assertEqual(self.mastery.mastery_score(perfect), 100)
        self.assertEqual(self.mastery.mastery_score(zero), 0)

    def test_not_enough_attempts_gives_none(self):
        self.assertIsNone(self.mastery.mastery_score(fake_stats(total_attempts=2)))
        self.assertIsNotNone(self.mastery.mastery_score(fake_stats(total_attempts=3)))

    @override_settings(MIN_ATTEMPTS_PER_TOPIC=5)
    def test_minimum_comes_from_settings(self):
        self.assertIsNone(self.mastery.mastery_score(fake_stats(total_attempts=4)))

    @override_settings(MASTERY_WEIGHTS={"accuracy": 1.0, "recent_accuracy": 0, "speed": 0, "attempt_efficiency": 0})
    def test_weights_come_from_settings(self):
        self.assertEqual(self.mastery.mastery_score(fake_stats()), 80)

    def test_learning_level_boundaries(self):
        level = self.mastery.learning_level
        self.assertEqual(level(0), "Beginner")
        self.assertEqual(level(39.99), "Beginner")
        self.assertEqual(level(40), "Intermediate")
        self.assertEqual(level(70), "Intermediate")
        self.assertEqual(level(70.01), "Advanced")
        self.assertEqual(level(100), "Advanced")

    def test_no_score_means_not_enough_data(self):
        self.assertEqual(self.mastery.learning_level(None), NOT_ENOUGH_DATA)
        self.assertEqual(NOT_ENOUGH_DATA, "Not enough data")  # same words as the roadmap page

    def test_same_stats_always_give_the_same_score(self):
        self.assertEqual(self.mastery.mastery_score(fake_stats()), self.mastery.mastery_score(fake_stats()))

    def test_end_to_end_with_real_attempts(self):
        c = make_catalogue()
        student = make_student()
        AttemptLog(student).many(c.easy1, "CCC", secs=100)
        stats = PerformanceAnalyzer().topic_stats(student, c.arrays)
        # 3 correct attempts, all quick, on a problem solved at the first try: a perfect 100
        self.assertEqual(self.mastery.mastery_score(stats), 100)
