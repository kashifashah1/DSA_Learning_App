"""Tests for SuccessPredictor: training, saving, loading, availability and predicting (Step 9)."""

import math
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import joblib
import numpy as np
import pandas as pd
from django.test import TestCase, override_settings
from sklearn.pipeline import Pipeline

from attempts.factories import AttemptLog, make_catalogue
from attempts.tests import make_student

from . import ml
from .ml import (
    LOGISTIC, TREE, ModelScore, ModelTrainingError, ModelUnavailableError, SuccessPredictor, choose_best,
)
from .services import FEATURE_COLUMNS


def make_training_df(rows=400, seed=0, flip=False, gaps=True):
    """Made-up attempts where mastery, recent accuracy and easy problems really lead to success."""
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        "topic_mastery": rng.uniform(0, 100, rows),
        "recent_accuracy": rng.uniform(0, 1, rows),
        "avg_time_sec": rng.uniform(60, 900, rows),
        "difficulty": rng.integers(0, 3, rows),
    })
    logit = 0.05 * (frame["topic_mastery"] - 50) + 2.5 * (frame["recent_accuracy"] - 0.5) - 1.0 * frame["difficulty"] + 0.4
    solved = (rng.uniform(size=rows) < 1 / (1 + np.exp(-logit))).astype(int)
    frame["solved"] = 1 - solved if flip else solved
    if gaps:  # real data has gaps: the model must cope with them
        frame.loc[frame.sample(frac=0.15, random_state=seed).index, "topic_mastery"] = np.nan
    return frame


GOOD = {"topic_mastery": 90, "recent_accuracy": 0.95, "avg_time_sec": 100, "difficulty": 0}
HARD = {"topic_mastery": 10, "recent_accuracy": 0.05, "avg_time_sec": 800, "difficulty": 2}


class ModelTestBase(TestCase):
    """Every test gets its own empty model folder, so it never touches a real model."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="dsa_ml_test_"))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.model_path = self.folder / "models" / "success_model.joblib"  # the folder does not exist yet
        override = override_settings(MODEL_PATH=self.model_path)
        override.enable()
        self.addCleanup(override.disable)
        ml._MODEL_CACHE.clear()
        self.addCleanup(ml._MODEL_CACHE.clear)

    def train(self, **kwargs):
        return SuccessPredictor().train(make_training_df(**kwargs))


class TrainingTests(ModelTestBase):
    def test_both_models_are_trained_and_compared(self):
        report = self.train()
        self.assertEqual([score.name for score in report.scores], [LOGISTIC, TREE])
        for score in report.scores:
            self.assertTrue(0 <= score.accuracy <= 1)
            self.assertTrue(0 <= score.f1 <= 1)

    def test_the_better_model_is_kept(self):
        report = self.train()
        self.assertEqual(report.chosen, choose_best(report.scores).name)
        self.assertEqual(joblib.load(self.model_path)["model_name"], report.chosen)

    def test_attempts_are_split_into_train_and_test(self):
        report = self.train(rows=400)
        self.assertEqual(report.rows, 400)
        self.assertEqual(report.train_rows + report.test_rows, 400)
        self.assertEqual(report.test_rows, 100)  # MODEL_TEST_SIZE = 0.25
        self.assertEqual(report.solved_rows, int(make_training_df(rows=400)["solved"].sum()))

    def test_the_model_learns_something_from_data_that_has_a_pattern(self):
        report = self.train()
        self.assertGreater(max(score.accuracy for score in report.scores), 0.65)

    def test_the_file_is_saved_at_the_path_from_settings_and_the_folder_is_created(self):
        self.assertFalse(self.model_path.parent.exists())
        report = self.train()
        self.assertTrue(self.model_path.exists())
        self.assertEqual(report.path, str(self.model_path))

    def test_the_saved_file_is_a_scikit_learn_pipeline_with_its_features(self):
        self.train()
        payload = joblib.load(self.model_path)
        self.assertIsInstance(payload["pipeline"], Pipeline)
        self.assertEqual(payload["feature_columns"], FEATURE_COLUMNS)
        self.assertEqual(set(payload["metrics"]), {LOGISTIC, TREE})
        self.assertEqual(payload["rows"], 400)
        self.assertIn("trained_at", payload)

    def test_notes_are_stored_in_the_file(self):
        SuccessPredictor().train(make_training_df(), notes={"contains_demo_data": True, "demo_rows": 7})
        self.assertEqual(SuccessPredictor().info()["notes"], {"contains_demo_data": True, "demo_rows": 7})

    def test_no_temporary_files_are_left_behind(self):
        self.train()
        self.assertEqual([p.name for p in self.model_path.parent.iterdir()], ["success_model.joblib"])

    def test_training_twice_on_the_same_data_gives_the_same_result(self):
        first = self.train()
        predictor = SuccessPredictor()
        predictor.load()
        before = [predictor.predict_probability(GOOD), predictor.predict_probability(HARD)]
        second = self.train()
        predictor = SuccessPredictor()
        predictor.load()
        after = [predictor.predict_probability(GOOD), predictor.predict_probability(HARD)]
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(before, after)

    def test_a_decision_tree_is_small(self):
        self.train()
        pipeline = joblib.load(self.model_path)["pipeline"]
        if pipeline.named_steps["model"].__class__.__name__ == "DecisionTreeClassifier":
            self.assertLessEqual(pipeline.named_steps["model"].get_depth(), 4)  # TREE_MAX_DEPTH


class ChooseBestTests(TestCase):
    def test_higher_f1_wins(self):
        scores = [ModelScore(LOGISTIC, 0.9, 0.70), ModelScore(TREE, 0.5, 0.80)]
        self.assertEqual(choose_best(scores).name, TREE)

    def test_equal_f1_goes_to_the_higher_accuracy(self):
        scores = [ModelScore(LOGISTIC, 0.70, 0.8), ModelScore(TREE, 0.75, 0.8)]
        self.assertEqual(choose_best(scores).name, TREE)

    def test_a_complete_tie_goes_to_the_simpler_logistic_regression(self):
        scores = [ModelScore(TREE, 0.7, 0.8), ModelScore(LOGISTIC, 0.7, 0.8)]
        self.assertEqual(choose_best(scores).name, LOGISTIC)


class TrainingRefusalTests(ModelTestBase):
    def assert_refused(self, frame, text):
        with self.assertRaises(ModelTrainingError) as caught:
            SuccessPredictor().train(frame)
        self.assertIn(text, str(caught.exception))
        self.assertFalse(self.model_path.exists())  # nothing was saved

    def test_only_solved_attempts(self):
        frame = make_training_df()
        frame["solved"] = 1
        self.assert_refused(frame, "both solved and not-solved")

    def test_only_not_solved_attempts(self):
        frame = make_training_df()
        frame["solved"] = 0
        self.assert_refused(frame, "both solved and not-solved")

    def test_too_few_of_one_kind(self):
        frame = make_training_df()
        frame["solved"] = 0
        frame.loc[frame.index[:4], "solved"] = 1  # only 4 solved; 5 are needed
        self.assert_refused(frame, "Found 4 solved")

    def test_missing_columns(self):
        self.assert_refused(make_training_df().drop(columns=["difficulty"]), "difficulty")

    def test_empty_data(self):
        self.assert_refused(make_training_df().iloc[0:0], "both solved and not-solved")


class LoadingAndAvailabilityTests(ModelTestBase):
    def test_missing_file_is_not_an_error(self):
        predictor = SuccessPredictor()
        self.assertFalse(predictor.load())
        self.assertFalse(predictor.is_available())

    def test_a_good_file_loads(self):
        self.train()
        self.assertTrue(SuccessPredictor().load())

    def write(self, payload=None, raw=None):
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            self.model_path.write_bytes(raw)
        else:
            joblib.dump(payload, self.model_path)

    def test_a_damaged_file_does_not_raise_and_is_logged(self):
        self.write(raw=b"this is not a model file at all")
        with self.assertLogs("analytics.ml", level="WARNING"):
            self.assertFalse(SuccessPredictor().load())
        self.assertFalse(SuccessPredictor().is_available())

    def test_an_empty_file(self):
        self.write(raw=b"")
        with self.assertLogs("analytics.ml", level="WARNING"):
            self.assertFalse(SuccessPredictor().load())

    def test_a_file_with_the_wrong_content(self):
        for payload in ({"unexpected": 1}, [1, 2, 3], "text", {"pipeline": object(), "feature_columns": FEATURE_COLUMNS}):
            with self.subTest(payload=repr(payload)):
                ml._MODEL_CACHE.clear()
                self.write(payload)
                with self.assertLogs("analytics.ml", level="WARNING"):
                    self.assertFalse(SuccessPredictor().load())

    def test_a_model_made_for_other_features_is_refused(self):
        self.train()
        payload = joblib.load(self.model_path)
        payload["feature_columns"] = ["something", "else"]
        ml._MODEL_CACHE.clear()
        self.write(payload)
        with self.assertLogs("analytics.ml", level="WARNING"):
            self.assertFalse(SuccessPredictor().load())

    def test_a_bad_file_is_logged_once_not_for_every_request(self):
        self.write(raw=b"garbage")
        with self.assertLogs("analytics.ml", level="WARNING") as logs:
            for _ in range(5):
                SuccessPredictor().load()
        self.assertEqual(len(logs.records), 1)

    def test_a_good_file_replaces_a_bad_one(self):
        self.write(raw=b"garbage")
        with self.assertLogs("analytics.ml", level="WARNING"):
            self.assertFalse(SuccessPredictor().load())
        self.train()  # `train_model` writes a new file
        self.assertTrue(SuccessPredictor().load())

    def test_available_needs_enough_stored_attempts(self):
        self.train()
        c, student = make_catalogue(), make_student()
        AttemptLog(student).many(c.easy1, "CFC")  # 3 attempts are stored
        predictor = SuccessPredictor()
        with override_settings(MIN_ATTEMPTS_FOR_MODEL=4):
            self.assertFalse(predictor.is_available())  # the file is fine, the data is not enough
        with override_settings(MIN_ATTEMPTS_FOR_MODEL=3):
            self.assertTrue(predictor.is_available())  # exactly the minimum is enough
        with override_settings(MIN_ATTEMPTS_FOR_MODEL=2):
            self.assertTrue(predictor.is_available())

    def test_not_available_without_a_file_even_with_enough_attempts(self):
        c, student = make_catalogue(), make_student()
        AttemptLog(student).many(c.easy1, "CFCCC")
        with override_settings(MIN_ATTEMPTS_FOR_MODEL=1):
            self.assertFalse(SuccessPredictor().is_available())

    def test_the_default_minimum_is_100(self):
        from django.conf import settings

        self.assertEqual(settings.MIN_ATTEMPTS_FOR_MODEL, 100)

    def test_is_available_never_raises(self):
        self.train()
        with mock.patch.object(ml.Attempt.objects, "count", side_effect=RuntimeError("database problem")):
            with self.assertLogs("analytics.ml", level="ERROR"):
                self.assertFalse(SuccessPredictor().is_available())

    def test_a_new_file_is_picked_up_without_restarting(self):
        self.train(flip=False)
        first = SuccessPredictor()
        first.load()
        before = first.predict_probability(GOOD)
        self.train(flip=True)  # the opposite pattern, saved to the same path
        second = SuccessPredictor()
        second.load()
        self.assertGreater(before, 0.5)
        self.assertLess(second.predict_probability(GOOD), 0.5)


class PredictionTests(ModelTestBase):
    def setUp(self):
        super().setUp()
        self.train()
        self.predictor = SuccessPredictor()
        self.predictor.load()

    def test_probabilities_are_between_0_and_1(self):
        for features in (GOOD, HARD, {"topic_mastery": 50, "recent_accuracy": 0.5, "avg_time_sec": 300, "difficulty": 1},
                         {"topic_mastery": 1e9, "recent_accuracy": 5, "avg_time_sec": -50, "difficulty": 7}):
            probability = self.predictor.predict_probability(features)
            self.assertIsInstance(probability, float)
            self.assertTrue(0.0 <= probability <= 1.0, probability)

    def test_a_strong_student_on_an_easy_problem_is_more_likely_to_succeed(self):
        self.assertGreater(self.predictor.predict_probability(GOOD), self.predictor.predict_probability(HARD))

    def test_harder_problems_lower_the_chance(self):
        chances = [
            self.predictor.predict_probability({**GOOD, "topic_mastery": 60, "recent_accuracy": 0.6, "difficulty": d})
            for d in (0, 1, 2)
        ]
        self.assertGreater(chances[0], chances[2])

    def test_missing_values_are_filled_in_not_an_error(self):
        for features in (
            {"topic_mastery": math.nan, "recent_accuracy": math.nan, "avg_time_sec": math.nan, "difficulty": 1},
            {"topic_mastery": None, "recent_accuracy": None, "avg_time_sec": None, "difficulty": 0},
            {"difficulty": 2},
        ):
            self.assertTrue(0.0 <= self.predictor.predict_probability(features) <= 1.0)

    def test_the_same_input_always_gives_the_same_probability(self):
        self.assertEqual(self.predictor.predict_probability(GOOD), self.predictor.predict_probability(GOOD))

    def test_predicting_without_a_model_raises_a_clear_error(self):
        os.remove(self.model_path)
        ml._MODEL_CACHE.clear()
        with self.assertRaises(ModelUnavailableError):
            SuccessPredictor().predict_probability(GOOD)

    def test_predicting_loads_the_model_by_itself(self):
        fresh = SuccessPredictor()  # load() was not called
        self.assertTrue(0.0 <= fresh.predict_probability(GOOD) <= 1.0)
