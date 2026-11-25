"""Tests for the stored TopicPerformance, overall skill, difficulty accuracy, trend and weak/strong topics."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from attempts.factories import NOW, AttemptLog, make_catalogue
from attempts.tests import make_student
from web.submission import SubmissionService
from web.test_submission_service import FakeEvaluator, add_cases, clock  # scripted evaluator, no process

from .models import TopicPerformance
from .services import PerformanceAnalyzer


class PerformanceTestBase(TestCase):
    def setUp(self):
        self.cat = make_catalogue()
        self.student = make_student()
        self.log = AttemptLog(self.student)
        self.analyzer = PerformanceAnalyzer()


class UpdateTopicPerformanceTests(PerformanceTestBase):
    def test_stores_one_row_with_the_calculated_numbers(self):
        self.log.many(self.cat.easy1, "CCFC")
        row = self.analyzer.update_topic_performance(self.student, self.cat.arrays)
        self.assertEqual(TopicPerformance.objects.count(), 1)
        self.assertEqual((row.student, row.topic, row.total_attempts), (self.student, self.cat.arrays, 4))
        self.assertAlmostEqual(row.accuracy, 0.75)
        self.assertIsNotNone(row.mastery_score)
        self.assertIn(row.learning_level, ["Beginner", "Intermediate", "Advanced"])
        self.assertIsNotNone(row.last_practised)

    def test_updating_again_changes_the_same_row_not_a_second_one(self):
        self.log.many(self.cat.easy1, "CCC")
        self.analyzer.update_topic_performance(self.student, self.cat.arrays)
        self.log.many(self.cat.easy2, "F")
        self.analyzer.update_topic_performance(self.student, self.cat.arrays)
        self.assertEqual(TopicPerformance.objects.count(), 1)
        self.assertEqual(TopicPerformance.objects.get().total_attempts, 4)

    def test_fewer_than_the_minimum_attempts_means_no_mastery(self):
        self.log.many(self.cat.easy1, "CC")  # MIN_ATTEMPTS_PER_TOPIC is 3
        row = self.analyzer.update_topic_performance(self.student, self.cat.arrays)
        self.assertIsNone(row.mastery_score)
        self.assertEqual(row.learning_level, "Not enough data")

    def test_only_the_asked_student_and_topic_are_touched(self):
        other = make_student("other@example.com")
        AttemptLog(other).many(self.cat.s_easy, "CCC")
        self.log.many(self.cat.easy1, "CCC")
        self.log.many(self.cat.s_easy, "FFF")
        self.analyzer.update_topic_performance(self.student, self.cat.arrays)
        # Only (student, Arrays) was written: no row for Strings, none for the other student.
        self.assertEqual(
            list(TopicPerformance.objects.values_list("student_id", "topic_id")),
            [(self.student.pk, self.cat.arrays.pk)],
        )

    def test_a_topic_without_attempts_has_no_row(self):
        self.assertIsNone(self.analyzer.update_topic_performance(self.student, self.cat.graphs))
        self.assertEqual(TopicPerformance.objects.count(), 0)

    def test_same_attempts_always_give_the_same_scores(self):
        self.log.many(self.cat.easy1, "CFCCF", secs=120)
        first = self.analyzer.update_topic_performance(self.student, self.cat.arrays)
        numbers = (first.mastery_score, first.accuracy, first.recent_accuracy, first.avg_time_sec)
        for _ in range(3):
            again = self.analyzer.update_topic_performance(self.student, self.cat.arrays)
            self.assertEqual((again.mastery_score, again.accuracy, again.recent_accuracy, again.avg_time_sec), numbers)

    def test_a_recent_decline_is_visible_in_the_stored_row(self):
        self.log.many(self.cat.easy1, "CCCCCC")
        self.log.many(self.cat.easy2, "FFFFF")  # the last RECENT_WINDOW (5) attempts all failed
        row = self.analyzer.update_topic_performance(self.student, self.cat.arrays)
        self.assertEqual(row.recent_accuracy, 0)
        self.assertGreater(row.accuracy, row.recent_accuracy)

    def test_sync_student_rebuilds_every_topic(self):
        self.log.many(self.cat.easy1, "CCC")
        self.log.many(self.cat.s_easy, "CFC")
        rows = self.analyzer.sync_student(self.student)
        self.assertEqual(len(rows), 2)
        TopicPerformance.objects.all().delete()
        self.analyzer.sync_student(self.student)
        self.assertEqual(TopicPerformance.objects.count(), 2)


class SubmissionHookTests(PerformanceTestBase):
    def test_a_submission_updates_the_topic_performance(self):
        problem = self.cat.easy1
        add_cases(problem, count=2, samples=1)
        service = SubmissionService(evaluator=FakeEvaluator(), clock=clock)
        for _ in range(3):
            service.submit(self.student, problem, "print(1)")
        row = TopicPerformance.objects.get(student=self.student, topic=self.cat.arrays)
        self.assertEqual(row.total_attempts, 3)
        self.assertIsNotNone(row.mastery_score)
        self.assertEqual(TopicPerformance.objects.count(), 1)  # no other topic was touched


class DerivedNumbersTests(PerformanceTestBase):
    def test_attempts_dataframe_has_only_this_students_attempts_in_order(self):
        AttemptLog(make_student("other@example.com")).many(self.cat.easy1, "CCC")
        self.log.many(self.cat.easy1, "CF")
        df = self.analyzer.attempts_dataframe(self.student)
        self.assertEqual(len(df), 2)
        self.assertEqual(list(df["is_correct"]), [True, False])
        self.assertTrue(df["submitted_at"].is_monotonic_increasing)

    def test_dataframe_of_a_student_without_attempts_is_empty_with_columns(self):
        df = self.analyzer.attempts_dataframe(self.student)
        self.assertTrue(df.empty)
        self.assertIn("is_correct", df.columns)

    def test_difficulty_accuracy(self):
        self.log.many(self.cat.easy1, "CC")
        self.log.many(self.cat.medium, "CF")
        rows = {row["difficulty"]: row for row in self.analyzer.difficulty_accuracy(self.student)}
        self.assertEqual(rows["Easy"]["accuracy"], 1.0)
        self.assertEqual((rows["Medium"]["attempts"], rows["Medium"]["accuracy"]), (2, 0.5))
        self.assertEqual((rows["Hard"]["attempts"], rows["Hard"]["accuracy"]), (0, None))

    def test_difficulty_accuracy_without_attempts(self):
        rows = self.analyzer.difficulty_accuracy(self.student)
        self.assertEqual([r["difficulty"] for r in rows], ["Easy", "Medium", "Hard"])
        self.assertTrue(all(r["accuracy"] is None for r in rows))

    def test_accuracy_trend_groups_by_day_and_accumulates(self):
        self.log.at(days_ago=3).many(self.cat.easy1, "CF")  # day 1: 1 of 2
        self.log.at(days_ago=2).many(self.cat.easy2, "CC")  # day 2: 2 of 2 -> overall 3 of 4
        trend = self.analyzer.accuracy_trend(self.student)
        self.assertEqual(len(trend), 2)
        self.assertEqual((trend[0]["attempts"], trend[0]["daily_accuracy"], trend[0]["cumulative_accuracy"]), (2, 0.5, 0.5))
        self.assertEqual((trend[1]["daily_accuracy"], trend[1]["cumulative_accuracy"]), (1.0, 0.75))
        self.assertLess(trend[0]["date"], trend[1]["date"])

    def test_accuracy_trend_empty(self):
        self.assertEqual(self.analyzer.accuracy_trend(self.student), [])

    def test_overall_skill_is_the_average_of_topics_with_enough_data(self):
        self.assertIsNone(self.analyzer.overall_skill(self.student))
        self.log.many(self.cat.easy1, "CCC")
        self.log.many(self.cat.s_easy, "FFF")
        self.log.many(self.cat.g_easy, "C")  # too few attempts: not counted
        stats = self.analyzer.all_topic_stats(self.student)
        scores = [self.analyzer.mastery.mastery_score(s) for s in stats.values()]
        scores = [s for s in scores if s is not None]
        self.assertEqual(len(scores), 2)
        self.assertAlmostEqual(self.analyzer.overall_skill(self.student), round(sum(scores) / 2, 2), places=2)


class WeakAndStrongTopicsTests(PerformanceTestBase):
    def build(self):
        self.log.many(self.cat.easy1, "CCCCC")  # Arrays: strong
        self.log.many(self.cat.s_easy, "FFFFF")  # Strings: weak
        self.analyzer.sync_student(self.student)

    def test_weak_and_strong_topics_are_picked_by_mastery(self):
        self.build()
        self.assertEqual([r.topic for r in self.analyzer.strong_topics(self.student)], [self.cat.arrays])
        self.assertEqual([r.topic for r in self.analyzer.weak_topics(self.student)], [self.cat.strings])

    def test_topics_without_enough_data_are_ignored(self):
        self.log.many(self.cat.easy1, "CC")
        self.analyzer.sync_student(self.student)
        self.assertEqual(self.analyzer.strong_topics(self.student), [])
        self.assertEqual(self.analyzer.weak_topics(self.student), [])

    def test_a_topic_is_never_weak_and_strong_at_once(self):
        self.log.many(self.cat.easy1, "CCCFC")
        self.log.many(self.cat.s_easy, "CFCFC")
        self.log.many(self.cat.g_easy, "CCFFC")
        strong = {r.topic_id for r in self.analyzer.strong_topics(self.student)}
        weak = {r.topic_id for r in self.analyzer.weak_topics(self.student)}
        self.assertFalse(strong & weak)

    def test_a_single_beginner_topic_is_weak_not_strong(self):
        self.log.many(self.cat.easy1, "FFFFF")
        self.assertEqual(self.analyzer.strong_topics(self.student), [])
        self.assertEqual([r.topic for r in self.analyzer.weak_topics(self.student)], [self.cat.arrays])

    def test_missing_rows_are_built_from_the_attempts(self):
        self.log.many(self.cat.easy1, "CCCCC")  # attempts exist, nothing stored yet
        self.assertEqual(TopicPerformance.objects.count(), 0)
        self.assertEqual(len(self.analyzer.strong_topics(self.student)), 1)
        self.assertEqual(TopicPerformance.objects.count(), 1)

    def test_only_own_rows_are_used(self):
        other = make_student("other@example.com")
        AttemptLog(other).many(self.cat.easy1, "CCCCC")
        PerformanceAnalyzer().sync_student(other)
        self.assertEqual(self.analyzer.strong_topics(self.student), [])


class RebuildCommandTests(PerformanceTestBase):
    def test_rebuild_performance_fills_the_table(self):
        self.log.many(self.cat.easy1, "CCC")
        out = StringIO()
        call_command("rebuild_performance", stdout=out)
        self.assertEqual(TopicPerformance.objects.count(), 1)
        self.assertIn("Rebuilt 1", out.getvalue())
