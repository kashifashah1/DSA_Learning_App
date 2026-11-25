"""Tests for PerformanceAnalyzer.build_training_data and prediction_features (Step 9)."""

import math

from django.test import TestCase

from attempts.factories import AttemptLog, make_catalogue
from attempts.tests import make_student

from .services import DIFFICULTY_CODE, FEATURE_COLUMNS, MasteryCalculator, PerformanceAnalyzer

HISTORY_COLUMNS = ["topic_mastery", "recent_accuracy", "avg_time_sec"]


def isnan(value):
    return isinstance(value, float) and math.isnan(value)


class TrainingDataTestBase(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.student = make_student()
        self.log = AttemptLog(self.student)
        self.analyzer = PerformanceAnalyzer()

    def data(self):
        return self.analyzer.build_training_data()

    def student_rows(self, student=None):
        frame = self.data()
        return frame[frame["student_id"] == (student or self.student).pk].reset_index(drop=True)


class ShapeTests(TrainingDataTestBase):
    def test_no_attempts_gives_an_empty_table_with_the_right_columns(self):
        frame = self.data()
        self.assertEqual(len(frame), 0)
        self.assertEqual(list(frame.columns), ["attempt_id", "student_id", *FEATURE_COLUMNS, "solved"])

    def test_feature_columns_are_the_four_from_the_plan(self):
        self.assertEqual(FEATURE_COLUMNS, ["topic_mastery", "recent_accuracy", "avg_time_sec", "difficulty"])

    def test_one_row_for_every_attempt(self):
        self.log.many(self.c.easy1, "CFC")
        self.log.many(self.c.s_easy, "FF")
        other = make_student("other@example.com")
        AttemptLog(other).many(self.c.easy1, "CCCC")
        self.assertEqual(len(self.data()), 9)

    def test_label_is_solved_or_not_solved(self):
        attempts = self.log.many(self.c.easy1, "CFFC")
        self.assertEqual(list(self.student_rows()["solved"]), [1, 0, 0, 1])
        self.assertEqual(list(self.student_rows()["attempt_id"]), [a.pk for a in attempts])

    def test_rows_come_in_a_fixed_order(self):
        self.log.many(self.c.easy1, "CFC")
        self.assertTrue(self.data().equals(self.data()))  # (equals() treats missing values as equal)

    def test_difficulty_is_encoded_as_a_number(self):
        self.log.add(self.c.easy1, True)
        self.log.add(self.c.medium, True)
        self.log.add(self.c.hard, True)
        self.assertEqual(list(self.student_rows()["difficulty"]), [0, 1, 2])
        self.assertEqual(DIFFICULTY_CODE, {"Easy": 0, "Medium": 1, "Hard": 2})

    def test_difficulty_is_the_one_copied_at_attempt_time(self):
        self.log.add(self.c.easy1, True)
        self.c.easy1.difficulty = "Hard"  # the administrator changes it later
        self.c.easy1.save()
        self.assertEqual(list(self.student_rows()["difficulty"]), [0])


class FeaturesUseOnlyThePastTests(TrainingDataTestBase):
    def test_the_first_attempt_in_a_topic_has_no_history(self):
        self.log.add(self.c.easy1, True)
        row = self.student_rows().iloc[0]
        for column in HISTORY_COLUMNS:
            self.assertTrue(isnan(row[column]), column)

    def test_the_second_attempt_knows_only_the_first(self):
        self.log.add(self.c.easy1, True, secs=120)
        self.log.add(self.c.easy2, False, secs=500)
        second = self.student_rows().iloc[1]
        self.assertEqual(second["recent_accuracy"], 1.0)  # the first attempt was correct
        self.assertEqual(second["avg_time_sec"], 120)  # not 310: its own 500 seconds are not included
        self.assertTrue(isnan(second["topic_mastery"]))  # fewer than MIN_ATTEMPTS_PER_TOPIC earlier attempts

    def test_mastery_appears_after_enough_earlier_attempts_and_matches_the_analyzer(self):
        self.log.many(self.c.easy1, "CFCC", secs=100)
        rows = self.student_rows()
        self.assertTrue(all(isnan(m) for m in rows["topic_mastery"][:3]))
        # the 4th attempt sees the first 3 attempts
        twin = make_student("twin@example.com")
        AttemptLog(twin).many(self.c.easy1, "CFC", secs=100)
        stats = self.analyzer.topic_stats(twin, self.c.arrays)
        self.assertEqual(rows["topic_mastery"][3], MasteryCalculator().mastery_score(stats))

    def test_recent_accuracy_uses_the_last_five_earlier_attempts(self):
        self.log.many(self.c.easy1, "CCFFFCC")  # the 7th attempt sees attempts 1 to 6
        seventh = self.student_rows().iloc[6]
        self.assertEqual(seventh["recent_accuracy"], 2 / 5)  # attempts 2 to 6: C F F F C

    def test_adding_later_attempts_never_changes_earlier_rows(self):
        self.log.many(self.c.easy1, "CFCFC")
        before = self.student_rows()
        self.log.many(self.c.easy2, "FFCCFFC")
        after = self.student_rows().iloc[: len(before)]
        for column in ["attempt_id", *FEATURE_COLUMNS, "solved"]:
            self.assertEqual(
                [None if isnan(v) else v for v in before[column]],
                [None if isnan(v) else v for v in after[column]],
                column,
            )

    def test_an_attempt_never_sees_its_own_outcome(self):
        twin = make_student("twin@example.com")
        AttemptLog(self.student).many(self.c.easy1, "CCFC")  # last attempt: correct
        AttemptLog(twin).many(self.c.easy1, "CCFF")  # same history, last attempt: wrong
        mine, theirs = self.student_rows().iloc[3], self.student_rows(twin).iloc[3]
        self.assertNotEqual(mine["solved"], theirs["solved"])
        for column in FEATURE_COLUMNS:
            self.assertEqual(
                None if isnan(mine[column]) else mine[column],
                None if isnan(theirs[column]) else theirs[column],
                column,
            )

    def test_topics_have_separate_histories(self):
        self.log.many(self.c.easy1, "CCCC", secs=100)  # Arrays
        self.log.add(self.c.s_easy, True)  # the first attempt in Strings: no Strings history yet
        strings_row = self.student_rows().iloc[4]
        self.assertTrue(isnan(strings_row["recent_accuracy"]))

    def test_students_have_separate_histories(self):
        AttemptLog(make_student("other@example.com")).many(self.c.easy1, "FFFF")
        self.log.add(self.c.easy1, True)
        self.assertTrue(isnan(self.student_rows().iloc[0]["recent_accuracy"]))


class PredictionFeaturesTests(TrainingDataTestBase):
    def test_no_history_gives_nan_and_the_difficulty_code(self):
        features = self.analyzer.prediction_features(None, "Medium")
        self.assertEqual(set(features), set(FEATURE_COLUMNS))
        self.assertEqual(features["difficulty"], 1)
        for column in HISTORY_COLUMNS:
            self.assertTrue(isnan(features[column]))

    def test_features_for_a_problem_match_the_row_that_attempt_would_get(self):
        """Training and predicting must describe the student in exactly the same way."""
        self.log.many(self.c.easy1, "CFCCF", secs=150)
        stats = self.analyzer.topic_stats(self.student, self.c.arrays)
        predicted = self.analyzer.prediction_features(stats, self.c.medium.difficulty)

        self.log.add(self.c.medium, True)  # now the attempt really happens
        row = self.student_rows().iloc[-1]
        for column in FEATURE_COLUMNS:
            self.assertEqual(predicted[column], row[column], column)

    def test_mastery_is_nan_until_there_are_enough_attempts(self):
        self.log.many(self.c.easy1, "CC")
        stats = self.analyzer.topic_stats(self.student, self.c.arrays)
        features = self.analyzer.prediction_features(stats, "Easy")
        self.assertTrue(isnan(features["topic_mastery"]))
        self.assertEqual(features["recent_accuracy"], 1.0)
