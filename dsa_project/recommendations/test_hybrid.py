"""Tests for the hybrid part of the engine: the model ranks the candidates, the rules are the safety net."""

import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from analytics.demo import generate_demo_data
from analytics.ml import SuccessPredictor
from analytics.services import PerformanceAnalyzer
from attempts.factories import NOW, AttemptLog, make_catalogue
from attempts.tests import make_student
from analytics import ml

from .engine import RecommendationEngine
from .models import Recommendation

Activity = Recommendation.Activity
RULE, MODEL = Recommendation.Source.RULE, Recommendation.Source.MODEL_ASSISTED


class FakePredictor:
    """A stand-in for the trained model, so the ranking can be tested exactly."""

    def __init__(self, by_difficulty=None, available=True, check_error=None, predict_error=None):
        self.by_difficulty = by_difficulty or {0: 0.9, 1: 0.8, 2: 0.6}
        self.available = available
        self.check_error = check_error
        self.predict_error = predict_error
        self.calls = []

    def is_available(self):
        if self.check_error:
            raise self.check_error
        return self.available

    def predict_probability(self, features):
        self.calls.append(dict(features))
        if self.predict_error:
            raise self.predict_error
        return self.by_difficulty[int(features["difficulty"])]


class HybridTestBase(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.student = make_student()
        self.log = AttemptLog(self.student)

    def engine(self, predictor=None):
        return RecommendationEngine(clock=lambda: NOW, predictor=predictor)

    def three_fast_easy_solutions(self, log=None):
        """A student ready for HARDER. The harder candidates are: medium, tp_medium, hard (in rule order)."""
        log = log or self.log
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            log.add(problem, True, secs=100)


class ModelRankingTests(HybridTestBase):
    def test_the_model_picks_the_candidate_closest_to_the_target(self):
        self.three_fast_easy_solutions()
        # medium 0.8 (0.20 away from the target 0.6), hard 0.6 (exactly on target)
        rec = self.engine(FakePredictor({1: 0.8, 2: 0.6})).recommend(self.student)
        self.assertEqual(rec.activity, Activity.HARDER)
        self.assertEqual(rec.problem, self.c.hard)  # the rules alone would offer medium
        self.assertEqual(rec.source, MODEL)

    def test_the_reason_mentions_the_model_and_the_estimate(self):
        self.three_fast_easy_solutions()
        rec = self.engine(FakePredictor({1: 0.8, 2: 0.6})).recommend(self.student)
        self.assertIn("harder problem", rec.reason)  # the rule's own reason is still there
        self.assertIn("Our model estimates about a 60% chance", rec.reason)
        self.assertIn("the target is 60%", rec.reason)

    def test_closest_means_closest_from_either_side(self):
        self.three_fast_easy_solutions()
        # medium 0.72 is 0.12 above the target; hard 0.50 is 0.10 below it
        rec = self.engine(FakePredictor({1: 0.72, 2: 0.50})).recommend(self.student)
        self.assertEqual(rec.problem, self.c.hard)
        rec = self.engine(FakePredictor({1: 0.68, 2: 0.50})).recommend(self.student)
        self.assertEqual(rec.problem, self.c.medium)  # 0.08 away beats 0.10 away

    def test_every_candidate_of_the_activity_is_scored(self):
        self.three_fast_easy_solutions()
        predictor = FakePredictor()
        self.engine(predictor).recommend(self.student)
        self.assertEqual(sorted(call["difficulty"] for call in predictor.calls), [1, 1, 2])  # medium, tp_medium, hard

    def test_equal_distances_keep_the_order_of_the_rules(self):
        self.three_fast_easy_solutions()
        rec = self.engine(FakePredictor({1: 0.6, 2: 0.6})).recommend(self.student)
        self.assertEqual(rec.problem, self.c.medium)  # first in the fixed rule order
        self.assertEqual(rec.source, MODEL)  # the model was asked, and it saw no difference

    @override_settings(TARGET_SUCCESS_PROB=0.85)
    def test_the_target_comes_from_settings(self):
        self.three_fast_easy_solutions()
        rec = self.engine(FakePredictor({1: 0.5, 2: 0.85})).recommend(self.student)
        self.assertEqual(rec.problem, self.c.hard)
        self.assertIn("the target is 85%", rec.reason)

    def test_a_different_target_gives_a_different_choice(self):
        self.three_fast_easy_solutions()
        probabilities = {1: 0.5, 2: 0.85}
        self.assertEqual(self.engine(FakePredictor(probabilities)).recommend(self.student).problem, self.c.medium)
        with override_settings(TARGET_SUCCESS_PROB=0.8):
            self.assertEqual(self.engine(FakePredictor(probabilities)).recommend(self.student).problem, self.c.hard)

    def test_the_model_receives_the_features_of_the_student_for_that_problem(self):
        self.three_fast_easy_solutions()
        predictor = FakePredictor()
        self.engine(predictor).recommend(self.student)
        stats = PerformanceAnalyzer().topic_stats(self.student, self.c.arrays)
        expected = PerformanceAnalyzer().prediction_features(stats, "Hard")
        hard_call = next(call for call in predictor.calls if call["difficulty"] == 2)
        self.assertEqual(hard_call, expected)

    def test_the_candidates_never_include_solved_problems(self):
        self.three_fast_easy_solutions()
        self.log.add(self.c.medium, True, secs=100)  # now medium is solved
        predictor = FakePredictor()
        rec = self.engine(predictor).recommend(self.student)
        self.assertNotEqual(rec.problem, self.c.medium)
        self.assertIn(rec.problem, (self.c.tp_medium, self.c.hard))

    def test_the_model_decides_in_the_same_way_every_time(self):
        self.three_fast_easy_solutions()
        picks = {self.engine(FakePredictor({1: 0.8, 2: 0.6})).recommend(self.student).problem_id for _ in range(4)}
        self.assertEqual(len(picks), 1)

    def test_two_students_with_the_same_history_get_the_same_choice(self):
        twin = make_student("twin@example.com")
        self.three_fast_easy_solutions()
        self.three_fast_easy_solutions(AttemptLog(twin))
        a = self.engine(FakePredictor({1: 0.8, 2: 0.6})).recommend(self.student)
        b = self.engine(FakePredictor({1: 0.8, 2: 0.6})).recommend(twin)
        self.assertEqual((a.activity, a.problem_id, a.reason, a.source), (b.activity, b.problem_id, b.reason, b.source))

    def test_the_stored_recommendation_says_it_is_model_assisted(self):
        self.three_fast_easy_solutions()
        self.engine(FakePredictor({1: 0.8, 2: 0.6})).recommend(self.student)
        self.assertEqual(Recommendation.objects.get().source, "MODEL_ASSISTED")


class FallbackToRulesTests(HybridTestBase):
    """Whatever is wrong with the model, the answer is the rules' answer, without an error."""

    def rules_answer(self):
        self.three_fast_easy_solutions()
        return RecommendationEngine(clock=lambda: NOW).recommend(self.student)  # a real predictor: no model file

    def test_no_model_file_means_the_rules(self):
        rec = self.rules_answer()
        self.assertEqual(rec.source, RULE)
        self.assertEqual(rec.problem, self.c.medium)
        self.assertNotIn("model", rec.reason.lower())

    def test_model_not_available_means_the_rules(self):
        self.three_fast_easy_solutions()
        predictor = FakePredictor({1: 0.8, 2: 0.6}, available=False)
        rec = self.engine(predictor).recommend(self.student)
        self.assertEqual((rec.source, rec.problem), (RULE, self.c.medium))
        self.assertEqual(predictor.calls, [])  # the model was not even asked

    def test_the_same_answer_as_without_any_model(self):
        self.three_fast_easy_solutions()
        without = self.engine().recommend(self.student)
        unavailable = self.engine(FakePredictor(available=False)).recommend(self.student)
        self.assertEqual((without.activity, without.problem, without.reason), (unavailable.activity, unavailable.problem, unavailable.reason))

    def test_a_model_that_fails_while_predicting_means_the_rules(self):
        self.three_fast_easy_solutions()
        with self.assertLogs("recommendations.engine", level="WARNING"):  # logged for us, not shown to the student
            rec = self.engine(FakePredictor(predict_error=RuntimeError("boom"))).recommend(self.student)
        self.assertEqual((rec.source, rec.problem), (RULE, self.c.medium))
        self.assertNotIn("model", rec.reason.lower())

    def test_a_check_that_fails_means_the_rules(self):
        self.three_fast_easy_solutions()
        with self.assertLogs("recommendations.engine", level="WARNING"):
            rec = self.engine(FakePredictor(check_error=RuntimeError("boom"))).recommend(self.student)
        self.assertEqual((rec.source, rec.problem), (RULE, self.c.medium))

    def test_one_candidate_means_nothing_to_rank(self):
        self.c.tp_easy.delete()
        self.log.many(self.c.easy1, "FC", secs=400)  # SAME level: only easy2 is left
        predictor = FakePredictor()
        rec = self.engine(predictor).recommend(self.student)
        self.assertEqual((rec.activity, rec.problem, rec.source), (Activity.SAME, self.c.easy2, RULE))
        self.assertEqual(predictor.calls, [])

    def test_a_new_student_always_gets_the_rule_for_new_students(self):
        predictor = FakePredictor({0: 0.1, 1: 0.6, 2: 0.9})
        rec = self.engine(predictor).recommend(self.student)
        self.assertEqual((rec.problem, rec.source), (self.c.easy1, RULE))  # the easiest problem, not "closest to 60%"
        self.assertEqual(predictor.calls, [])

    def test_revision_is_always_the_rule(self):
        self.log.at(days_ago=30).add(self.c.easy2, True)  # two solved problems to choose from
        self.log.at(days_ago=20).many(self.c.easy1, "CC")  # strong but forgotten
        predictor = FakePredictor({0: 0.6, 1: 0.6, 2: 0.6})
        rec = self.engine(predictor).recommend(self.student)
        self.assertEqual((rec.activity, rec.source), (Activity.REVISION, RULE))
        self.assertEqual(rec.problem, self.c.easy2)  # the one solved longest ago, as in Step 8
        self.assertEqual(predictor.calls, [])  # the model was not asked

    def test_the_rules_alone_still_work_when_the_model_is_available_but_has_no_candidates(self):
        for problem in (self.c.easy1, self.c.easy2, self.c.medium, self.c.hard, self.c.tp_easy, self.c.tp_medium,
                        self.c.s_easy, self.c.s_medium, self.c.g_easy, self.c.g_hard):
            self.log.add(problem, True)
        rec = self.engine(FakePredictor()).recommend(self.student)
        self.assertEqual(rec.activity, Activity.REVISION)  # everything is solved
        self.assertEqual(rec.source, RULE)

    def test_following_the_advice_never_offers_a_solved_problem_except_for_revision(self):
        engine = self.engine(FakePredictor({0: 0.75, 1: 0.55, 2: 0.4}))
        for step in range(14):
            solved = set(self.student.attempts.filter(is_correct=True).values_list("problem_id", flat=True))
            rec = engine.recommend(self.student)
            if rec.activity != Activity.REVISION:
                self.assertNotIn(rec.problem_id, solved, f"step {step}")
            self.log.add(rec.problem, step % 4 != 3, secs=100)


class RealPredictorTests(HybridTestBase):
    """The real SuccessPredictor, with a real model file in a temporary folder."""

    def setUp(self):
        super().setUp()
        self.folder = Path(tempfile.mkdtemp(prefix="dsa_hybrid_test_"))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.model_path = self.folder / "success_model.joblib"
        override = override_settings(MODEL_PATH=self.model_path)
        override.enable()
        self.addCleanup(override.disable)
        ml._MODEL_CACHE.clear()
        self.addCleanup(ml._MODEL_CACHE.clear)

    def train_on_demo_data(self):
        generate_demo_data(students=30, attempts_per_student=12, seed=3)  # 360 fake attempts
        SuccessPredictor().train(PerformanceAnalyzer().build_training_data())

    def recommend(self):
        return RecommendationEngine(clock=lambda: NOW).recommend(self.student)  # a real predictor, as in production

    def test_a_missing_model_file_means_the_rules_without_any_error(self):
        self.three_fast_easy_solutions()
        rec = self.recommend()
        self.assertEqual((rec.source, rec.problem), (RULE, self.c.medium))

    def test_a_damaged_model_file_means_the_rules_without_any_error(self):
        self.model_path.write_bytes(b"not a model")
        self.three_fast_easy_solutions()
        with self.assertLogs("analytics.ml", level="WARNING"):
            rec = self.recommend()
        self.assertEqual((rec.source, rec.problem), (RULE, self.c.medium))

    def test_a_good_model_is_not_used_below_the_minimum_number_of_attempts(self):
        self.train_on_demo_data()
        with override_settings(MIN_ATTEMPTS_FOR_MODEL=10_000):  # more than the stored attempts
            self.three_fast_easy_solutions()
            rec = self.recommend()
        self.assertEqual(rec.source, RULE)
        self.assertEqual(rec.problem, self.c.medium)

    def test_a_good_model_with_enough_attempts_is_used(self):
        self.train_on_demo_data()
        self.three_fast_easy_solutions()
        rec = self.recommend()
        self.assertEqual(rec.source, MODEL)
        self.assertEqual(rec.activity, Activity.HARDER)
        self.assertIn(rec.problem, (self.c.medium, self.c.tp_medium, self.c.hard))
        self.assertIn("Our model estimates about a", rec.reason)
        percent = int(rec.reason.split("about a ")[1].split("%")[0])
        self.assertTrue(0 <= percent <= 100)

    def test_the_real_model_ranks_with_probabilities_between_0_and_1(self):
        self.train_on_demo_data()
        self.three_fast_easy_solutions()
        engine = RecommendationEngine(clock=lambda: NOW)
        options = engine.candidate_problems(self.student, self.c.arrays, Activity.HARDER)
        pick = engine.rank_with_model(self.student, options)
        self.assertIn(pick.problem, options)
        self.assertTrue(0.0 <= pick.probability <= 1.0)

    def test_a_model_trained_on_other_features_is_ignored(self):
        self.train_on_demo_data()
        payload = ml.joblib.load(self.model_path)
        payload["feature_columns"] = ["x"]
        ml.joblib.dump(payload, self.model_path)
        ml._MODEL_CACHE.clear()
        self.three_fast_easy_solutions()
        with self.assertLogs("analytics.ml", level="WARNING"):
            self.assertEqual(self.recommend().source, RULE)

    def test_the_real_model_never_offers_a_solved_problem(self):
        self.train_on_demo_data()
        engine = RecommendationEngine(clock=lambda: NOW)
        for step in range(12):
            solved = set(self.student.attempts.filter(is_correct=True).values_list("problem_id", flat=True))
            rec = engine.recommend(self.student)
            if rec.activity != Activity.REVISION:
                self.assertNotIn(rec.problem_id, solved, f"step {step}")
            self.log.add(rec.problem, step % 3 != 2, secs=150)


class CardShowsTheSourceTests(HybridTestBase):
    def test_the_result_page_names_the_source(self):
        from django.core.management import call_command
        from io import StringIO
        from django.urls import reverse

        from attempts.tests import make_attempt
        from problems.models import Problem

        call_command("seed_problems", stdout=StringIO())
        problem = Problem.objects.get(title="Sum of Array")
        attempt = make_attempt(self.student, problem, attempt_no=1)
        self.client.force_login(self.student)
        url = f"{reverse('problem_detail', args=[problem.pk])}?attempt={attempt.pk}"

        Recommendation.objects.create(student=self.student, activity="SAME", problem=problem, reason="By rules.", source=RULE)
        self.assertContains(self.client.get(url), "Rule-based")
        Recommendation.objects.create(student=self.student, activity="SAME", problem=problem, reason="By model.", source=MODEL)
        page = self.client.get(url)
        self.assertContains(page, "Model-assisted")
        self.assertNotContains(page, "Rule-based")  # only the newest suggestion is shown
