"""Tests for the rule-based RecommendationEngine (Step 8), rule by rule."""

import time
from datetime import timedelta

from django.test import TestCase, override_settings

from analytics.services import PerformanceAnalyzer
from analytics.tests import fake_stats
from attempts.factories import NOW, AttemptLog, make_catalogue
from attempts.tests import make_student
from problems.models import Problem

from .engine import RecommendationEngine
from .models import Recommendation

Activity = Recommendation.Activity


class EngineTestBase(TestCase):
    def setUp(self):
        self.c = make_catalogue()
        self.student = make_student()
        self.log = AttemptLog(self.student)
        self.engine = RecommendationEngine(clock=lambda: NOW)

    def recommend(self, student=None):
        return self.engine.recommend(student or self.student)

    def assert_rec(self, rec, activity, problem=None, topic=None):
        self.assertEqual(rec.activity, activity, rec.reason)
        if problem is not None:
            self.assertEqual(rec.problem, problem, rec.reason)
        if topic is not None:
            self.assertEqual(rec.topic, topic)
        self.assertTrue(rec.reason.strip())  # always a reason in plain language


# ---------------------------------------------------------------- rule 1
class NewStudentTests(EngineTestBase):
    def test_easiest_problem_of_the_first_topic(self):
        rec = self.recommend()
        # Arrays has order 1 (it was created LAST); easiest problem, first subtopic, lowest id
        self.assert_rec(rec, Activity.NEXT_TOPIC, self.c.easy1, self.c.arrays)
        self.assertIn("new here", rec.reason)
        self.assertIn("Arrays", rec.reason)

    def test_first_topic_means_topic_order_not_creation_order(self):
        self.assertEqual(self.recommend().topic, self.c.arrays)
        self.assertNotEqual(self.c.arrays.pk, min(self.c.arrays.pk, self.c.strings.pk, self.c.graphs.pk))

    def test_a_topic_without_problems_is_skipped(self):
        from problems.models import Topic

        Topic.objects.create(name="Empty", order=0)  # first in the roadmap, but nothing to practise
        self.assertEqual(self.recommend().problem, self.c.easy1)

    def test_no_problems_at_all(self):
        Problem.objects.all().delete()
        rec = self.recommend()
        self.assertIsNone(rec.problem)
        self.assertIn("no problems", rec.reason.lower())

    def test_recommendation_is_stored(self):
        rec = self.recommend()
        saved = Recommendation.objects.get()
        self.assertEqual(saved, rec)
        self.assertEqual(saved.student, self.student)
        self.assertEqual(saved.source, "RULE")
        self.assertIsNotNone(saved.created_at)

    def test_every_call_stores_a_new_recommendation(self):
        self.recommend()
        self.recommend()
        self.assertEqual(Recommendation.objects.count(), 2)

    def test_choose_activity_and_candidates_for_a_new_student(self):
        choice = self.engine.choose_activity(self.student)
        self.assertEqual((choice.activity, choice.topic), (Activity.NEXT_TOPIC, self.c.arrays))
        Problem.objects.all().delete()
        self.assertIsNone(self.engine.choose_activity(self.student))


# ---------------------------------------------------------------- rule 2
class NeedsRevisionTests(TestCase):
    """The revision test itself, with ready-made statistics."""

    def setUp(self):
        self.engine = RecommendationEngine(clock=lambda: NOW)

    def check(self, **values):
        return self.engine.needs_revision(fake_stats(**values), NOW)

    def test_strong_topic_with_a_big_drop(self):
        self.assertTrue(self.check(baseline_accuracy=1.0, recent_accuracy=0.2))

    def test_drop_of_exactly_the_limit_counts_even_with_decimal_rounding(self):
        # 1.0 - 0.8 is 0.19999999999999996 in a computer: it must still count as 0.20
        self.assertTrue(self.check(baseline_accuracy=1.0, recent_accuracy=0.8))

    def test_small_drop_does_not_count(self):
        self.assertFalse(self.check(baseline_accuracy=0.75, recent_accuracy=0.6))

    def test_topic_that_was_not_strong_does_not_count(self):
        self.assertFalse(self.check(baseline_accuracy=0.6, recent_accuracy=0.0, accuracy=0.4))

    def test_strong_limit_is_inclusive(self):
        self.assertTrue(self.check(baseline_accuracy=0.7, recent_accuracy=0.4))
        self.assertFalse(self.check(baseline_accuracy=0.69, recent_accuracy=0.2))

    def test_no_baseline_and_not_stale_means_no_revision(self):
        self.assertFalse(self.check(baseline_accuracy=None, recent_accuracy=0.0, last_practised=NOW))

    def test_too_few_attempts_never_need_revision(self):
        self.assertFalse(self.check(total_attempts=2, baseline_accuracy=1.0, recent_accuracy=0.0))
        self.assertFalse(self.check(total_attempts=2, accuracy=1.0, last_practised=NOW - timedelta(days=99)))

    def test_not_practised_for_more_than_the_limit_of_days(self):
        self.assertFalse(self.check(accuracy=0.9, last_practised=NOW - timedelta(days=14)))  # exactly 14: not older
        self.assertTrue(self.check(accuracy=0.9, last_practised=NOW - timedelta(days=14, seconds=1)))

    def test_stale_topic_must_have_been_strong(self):
        self.assertTrue(self.check(accuracy=0.7, last_practised=NOW - timedelta(days=30)))
        self.assertFalse(self.check(accuracy=0.69, last_practised=NOW - timedelta(days=30)))

    @override_settings(REVISION_AFTER_DAYS=3, REVISION_ACCURACY_DROP=0.5)
    def test_limits_come_from_settings(self):
        self.assertTrue(self.check(accuracy=0.9, last_practised=NOW - timedelta(days=4)))
        self.assertFalse(self.check(baseline_accuracy=1.0, recent_accuracy=0.6))  # drop 0.4 < 0.5


class RevisionTests(EngineTestBase):
    def test_strong_topic_whose_recent_accuracy_dropped(self):
        self.log.many(self.c.easy1, "CCCC")  # strong before: 100% correct
        self.log.many(self.c.easy2, "CFFFF")  # the last 5 attempts: only 20% correct
        rec = self.recommend()
        # the solved problem that was solved the longest time ago
        self.assert_rec(rec, Activity.REVISION, self.c.easy1, self.c.arrays)
        self.assertIn("fell to 20%", rec.reason)
        self.assertIn("100%", rec.reason)

    def test_a_drop_of_exactly_twenty_percent_triggers_revision(self):
        self.log.many(self.c.easy1, "CCCCC")
        self.log.many(self.c.easy2, "CCCCF")  # recent accuracy 80%: a drop of exactly 0.20
        self.assert_rec(self.recommend(), Activity.REVISION)

    def test_a_smaller_drop_does_not(self):
        self.log.many(self.c.easy1, "CCCCCCCCCF")  # 90% before
        self.log.many(self.c.easy2, "CCCCF")  # 80% now: a drop of 0.10
        self.assertNotEqual(self.recommend().activity, Activity.REVISION)

    def test_topic_that_was_never_strong_gets_no_revision(self):
        self.log.many(self.c.easy1, "CFCFF")  # 40% before
        self.log.many(self.c.easy2, "FFFFF")
        self.assertNotEqual(self.recommend().activity, Activity.REVISION)

    def test_strong_topic_not_practised_for_over_14_days(self):
        self.log.at(days_ago=15).many(self.c.easy1, "CCC")
        rec = self.recommend()
        self.assert_rec(rec, Activity.REVISION, self.c.easy1, self.c.arrays)
        self.assertIn("over 14 days", rec.reason)

    def test_exactly_14_days_is_not_old_enough_but_one_minute_more_is(self):
        self.log.at(days_ago=14, minutes_ago=30).many(self.c.easy1, "CCC")  # last attempt: exactly 14 days ago
        self.assertNotEqual(self.recommend().activity, Activity.REVISION)
        Recommendation.objects.all().delete()
        other = make_student("other@example.com")
        AttemptLog(other).at(days_ago=14, minutes_ago=31).many(self.c.easy1, "CCC")  # 14 days and 1 minute
        self.assert_rec(self.recommend(other), Activity.REVISION)

    def test_stale_topic_that_was_weak_gets_no_revision(self):
        self.log.at(days_ago=40).many(self.c.easy1, "CFF")
        self.assertNotEqual(self.recommend().activity, Activity.REVISION)

    def test_too_few_attempts_get_no_revision(self):
        self.log.at(days_ago=40).many(self.c.easy1, "CC")
        self.assertNotEqual(self.recommend().activity, Activity.REVISION)

    def test_revision_comes_before_the_difficulty_rules(self):
        self.log.at(days_ago=20).many(self.c.easy1, "CCC")  # Arrays: strong but forgotten
        self.log.at(days_ago=0, minutes_ago=60).many(self.c.s_easy, "CCC", secs=100)  # Strings: going very well now
        self.assert_rec(self.recommend(), Activity.REVISION, topic=self.c.arrays)

    def test_first_topic_in_the_roadmap_is_revised_first(self):
        self.log.at(days_ago=20).many(self.c.s_easy, "CCC")  # Strings (order 2) first in time
        self.log.at(days_ago=19).many(self.c.easy1, "CCC")  # Arrays (order 1)
        self.assert_rec(self.recommend(), Activity.REVISION, topic=self.c.arrays)

    def test_revision_offers_the_solved_problem_that_is_oldest(self):
        self.log.at(days_ago=30).add(self.c.easy2, True)  # solved long ago
        self.log.at(days_ago=20).many(self.c.easy1, "CC")  # solved later
        self.assert_rec(self.recommend(), Activity.REVISION, self.c.easy2)

    def test_revision_is_the_one_case_where_a_solved_problem_is_offered(self):
        self.log.at(days_ago=20).many(self.c.easy1, "CCC")
        rec = self.recommend()
        self.assertEqual(rec.activity, Activity.REVISION)
        self.assertTrue(rec.problem.attempts.filter(student=self.student, is_correct=True).exists())


# ---------------------------------------------------------------- rule 3
class HarderTests(EngineTestBase):
    def test_several_recent_correct_and_fast_solutions(self):
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            self.log.add(problem, True, secs=100)  # well inside the 300 seconds expected for Easy
        rec = self.recommend()
        self.assert_rec(rec, Activity.HARDER, self.c.medium, self.c.arrays)  # the nearest harder level
        self.assertIn("correctly and quickly", rec.reason)

    def test_correct_but_slow_is_not_harder(self):
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            self.log.add(problem, True, secs=400)  # slower than the 300 seconds expected
        self.assertNotEqual(self.recommend().activity, Activity.HARDER)

    def test_two_fast_solutions_are_not_enough(self):
        self.log.add(self.c.easy1, True, secs=100)
        self.log.add(self.c.easy2, True, secs=100)
        self.log.add(self.c.tp_easy, False, secs=100)
        self.assertNotEqual(self.recommend().activity, Activity.HARDER)

    def test_the_newest_attempt_must_be_correct(self):
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            self.log.add(problem, True, secs=100)
        self.log.add(self.c.easy1, False, secs=100)
        self.assertNotEqual(self.recommend().activity, Activity.HARDER)

    def test_never_tried_problems_come_before_tried_ones(self):
        self.log.add(self.c.medium, False, secs=100)  # tried, not solved
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            self.log.add(problem, True, secs=100)
        # Medium (Traversal) comes first in roadmap order, but it was tried already
        self.assert_rec(self.recommend(), Activity.HARDER, self.c.tp_medium)

    def test_with_no_harder_problem_left_the_next_topic_is_suggested(self):
        self.log.many(self.c.hard, "CCC", secs=100)  # Hard is the top level and the mastery is very high
        rec = self.recommend()
        self.assert_rec(rec, Activity.NEXT_TOPIC, self.c.s_easy, self.c.strings)
        self.assertIn("mastery", rec.reason)

    def test_not_enough_attempts_in_the_topic_means_no_adjustment(self):
        self.log.add(self.c.easy1, True, secs=100)
        self.log.add(self.c.easy2, True, secs=100)  # only 2 attempts: fewer than MIN_ATTEMPTS_PER_TOPIC
        self.assert_rec(self.recommend(), Activity.SAME)

    @override_settings(HARDER_MIN_CORRECT=2)
    def test_number_of_correct_solutions_comes_from_settings(self):
        self.log.add(self.c.easy1, True, secs=100)
        self.log.add(self.c.easy2, True, secs=100)
        self.log.add(self.c.tp_easy, False, secs=100)
        self.log.add(self.c.easy1, True, secs=100)
        self.assert_rec(self.recommend(), Activity.HARDER)


class EasierTests(EngineTestBase):
    def test_repeated_failures(self):
        self.log.add(self.c.medium, False)
        self.log.add(self.c.tp_medium, False)
        self.log.add(self.c.medium, False)
        rec = self.recommend()
        self.assert_rec(rec, Activity.EASIER, self.c.easy1, self.c.arrays)  # nearest easier level, first in order
        self.assertIn("3 of your last 3", rec.reason)

    def test_two_failures_are_not_enough(self):
        self.log.add(self.c.medium, True)
        self.log.add(self.c.medium, False)
        self.log.add(self.c.tp_medium, False)
        self.assertNotEqual(self.recommend().activity, Activity.EASIER)

    def test_the_newest_attempt_must_have_failed(self):
        self.log.many(self.c.medium, "FFFC")
        self.assertNotEqual(self.recommend().activity, Activity.EASIER)

    def test_easy_problems_have_nothing_easier_so_the_same_level_is_offered(self):
        self.log.add(self.c.easy1, False)
        self.log.add(self.c.easy2, False)
        self.log.add(self.c.tp_easy, False)
        rec = self.recommend()
        self.assertEqual(rec.activity, Activity.SAME)
        self.assertEqual(rec.problem.difficulty, "Easy")

    def test_easier_never_picks_a_harder_problem(self):
        self.log.many(self.c.hard, "FFF")
        rec = self.recommend()
        self.assertEqual(rec.activity, Activity.EASIER)
        self.assertEqual(rec.problem.difficulty, "Medium")  # one level down

    @override_settings(EASIER_MIN_FAILURES=2)
    def test_number_of_failures_comes_from_settings(self):
        self.log.add(self.c.medium, True)
        self.log.add(self.c.medium, False)
        self.log.add(self.c.tp_medium, False)
        self.assert_rec(self.recommend(), Activity.EASIER)


class SameAndRelatedTests(EngineTestBase):
    def steady_results(self):
        """Mixed and slow results: not struggling, not flying, mastery below 70."""
        self.log.many(self.c.easy1, "FC", secs=400)
        self.log.many(self.c.easy2, "FC", secs=400)

    def test_steady_results_give_a_problem_at_the_same_level(self):
        self.steady_results()
        rec = self.recommend()
        self.assert_rec(rec, Activity.SAME, self.c.tp_easy, self.c.arrays)  # the only unsolved Easy problem
        self.assertIn("steady", rec.reason)

    def test_same_level_prefers_the_same_subtopic(self):
        self.log.add(self.c.easy2, False, secs=400)  # tried, not solved (Traversal)
        self.log.many(self.c.easy1, "FC", secs=400)  # the newest attempts are in Traversal
        rec = self.recommend()
        self.assert_rec(rec, Activity.SAME, self.c.easy2)  # not tp_easy, which is in another subtopic

    def test_related_practice_in_the_weakest_subtopic(self):
        self.log.add(self.c.tp_easy, False, secs=1000)
        self.log.add(self.c.tp_medium, False, secs=1000)
        for problem in (self.c.easy1, self.c.easy2, self.c.medium):
            self.log.add(problem, True, secs=1000)
        rec = self.recommend()
        # Two Pointers: 0% correct, the whole topic: 60%
        self.assert_rec(rec, Activity.RELATED, self.c.tp_easy, self.c.arrays)  # the easiest problem there
        self.assertIn("Two Pointers", rec.reason)
        self.assertIn("0%", rec.reason)
        self.assertIn("60%", rec.reason)

    def test_no_related_practice_when_no_subtopic_is_weaker_than_the_topic(self):
        self.steady_results()  # only one subtopic has attempts, so none is weaker than the whole topic
        self.assertNotEqual(self.recommend().activity, Activity.RELATED)

    def test_related_has_nothing_to_offer_when_the_subtopic_is_finished(self):
        for problem in (self.c.tp_easy, self.c.tp_medium):
            self.log.add(problem, True)
        picked = self.engine.pick_problem(self.student, self.c.arrays, Activity.RELATED, subtopic=self.c.pointers)
        self.assertIsNone(picked)


class NextTopicTests(EngineTestBase):
    def test_high_mastery_moves_on_when_nothing_harder_is_left(self):
        self.log.many(self.c.hard, "CCC", secs=100)
        rec = self.recommend()
        self.assert_rec(rec, Activity.NEXT_TOPIC, self.c.s_easy, self.c.strings)
        self.assertIn("100 out of 100", rec.reason)
        self.assertIn("Strings", rec.reason)

    def test_slow_but_accurate_students_also_move_on(self):
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            self.log.add(problem, True, secs=400)  # not fast, but mastery is still above 70
        self.assert_rec(self.recommend(), Activity.NEXT_TOPIC, self.c.s_easy)

    def test_the_next_topic_is_the_easiest_unsolved_problem_there(self):
        self.log.many(self.c.hard, "CCC", secs=100)
        self.assertEqual(self.recommend().problem.difficulty, "Easy")

    def test_a_finished_topic_is_skipped(self):
        self.log.add(self.c.s_easy, True)
        self.log.add(self.c.s_medium, True)  # Strings is completely solved
        self.log.many(self.c.hard, "CCC", secs=100)
        self.assert_rec(self.recommend(), Activity.NEXT_TOPIC, self.c.g_easy, self.c.graphs)

    def test_no_later_topic_left_goes_back_to_the_first_unsolved_problem_in_the_roadmap(self):
        for problem in (self.c.s_easy, self.c.s_medium, self.c.g_easy, self.c.g_hard):
            self.log.add(problem, True)  # Strings and Graphs are solved; the newest attempt is in Graphs
        rec = self.recommend()
        self.assert_rec(rec, Activity.NEXT_TOPIC, self.c.easy1, self.c.arrays)  # Arrays still has unsolved problems
        self.assertIn("next problem you have not solved", rec.reason)

    def test_low_mastery_does_not_move_on(self):
        self.log.many(self.c.easy1, "FFC", secs=1000)
        self.assertNotEqual(self.recommend().activity, Activity.NEXT_TOPIC)


class LevelUsedUpTests(EngineTestBase):
    """When the level is finished, stay in the topic and change level before changing topic."""

    def test_finished_easy_problems_lead_to_a_harder_one_in_the_same_topic(self):
        self.c.tp_easy.delete()  # Arrays now has only two Easy problems
        self.log.add(self.c.easy1, True, secs=400)
        self.log.add(self.c.easy2, True, secs=400)  # only 2 attempts: no difficulty adjustment yet
        rec = self.recommend()
        self.assert_rec(rec, Activity.HARDER, self.c.medium, self.c.arrays)
        self.assertIn("finished the Easy problems in Arrays", rec.reason)

    def test_finished_the_top_level_leads_to_an_easier_unsolved_one(self):
        self.log.add(self.c.hard, True)  # the only Hard problem in Arrays
        rec = self.recommend()
        self.assert_rec(rec, Activity.EASIER, self.c.medium, self.c.arrays)  # the nearest easier level first
        self.assertIn("no more Hard problems left in Arrays", rec.reason)

    @override_settings(MIN_ATTEMPTS_PER_TOPIC=10)  # no mastery yet, so only the level logic is at work
    def test_the_next_topic_comes_only_after_every_level_of_the_topic_is_used_up(self):
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            self.log.add(problem, True, secs=400)
        rec = self.recommend()
        self.assert_rec(rec, Activity.HARDER, self.c.medium, self.c.arrays)  # Arrays still has Medium and Hard problems

    def test_a_topic_that_is_completely_solved_moves_on(self):
        self.log.add(self.c.hard, True)
        for problem in (self.c.easy1, self.c.easy2, self.c.medium, self.c.tp_easy, self.c.tp_medium):
            self.log.add(problem, True)
        self.log.add(self.c.hard, True)  # newest attempt is in Arrays, and Arrays has nothing left
        rec = self.recommend()
        self.assertEqual(rec.topic, self.c.strings)

    @override_settings(MIN_ATTEMPTS_PER_TOPIC=10)
    def test_following_the_advice_finishes_the_topic_before_jumping_to_the_next(self):
        topics_in_order = []
        for step in range(7):
            rec = self.recommend()
            topics_in_order.append(rec.topic.name)
            self.log.add(rec.problem, True, secs=400)
        self.assertEqual(topics_in_order, ["Arrays"] * 6 + ["Strings"])  # 6 problems in Arrays, then Strings


class CurrentTopicTests(EngineTestBase):
    def test_rules_look_at_the_topic_practised_last(self):
        self.log.at(days_ago=2).many(self.c.easy1, "CCC", secs=100)  # Arrays, earlier
        self.log.at(days_ago=0, minutes_ago=60).many(self.c.s_easy, "CCC", secs=100)  # Strings, now
        rec = self.recommend()
        self.assert_rec(rec, Activity.HARDER, self.c.s_medium, self.c.strings)

    def test_the_topic_is_the_one_of_the_newest_attempt_even_if_the_other_has_more_attempts(self):
        self.log.at(days_ago=3).many(self.c.easy1, "FFFF")  # lots of failures in Arrays, but old
        self.log.at(days_ago=1).many(self.c.s_easy, "CCC", secs=100)
        self.assertEqual(self.recommend().topic, self.c.strings)


# ---------------------------------------------------------------- rule 4
class NeverRecommendSolvedTests(EngineTestBase):
    def follow(self, steps, outcome):
        """Do exactly what is recommended, again and again, and check rule 4 at every step."""
        recs = []
        for step in range(steps):
            solved = set(
                self.student.attempts.filter(is_correct=True).values_list("problem_id", flat=True)
            )
            rec = self.recommend()
            recs.append(rec)
            if rec.problem is None:
                break
            if rec.activity != Activity.REVISION:
                self.assertNotIn(rec.problem_id, solved, f"step {step}: {rec.activity} {rec.reason}")
            self.log.add(rec.problem, outcome(step), secs=100)
        return recs

    def test_following_every_recommendation_when_all_goes_well(self):
        recs = self.follow(14, outcome=lambda step: True)
        self.assertEqual(
            self.student.attempts.filter(is_correct=True).values("problem_id").distinct().count(), 10
        )  # all 10 problems get solved, one after the other
        self.assertEqual({r.activity for r in recs[10:]}, {Activity.REVISION})  # then only revision is left
        self.assertIn("solved every problem", recs[-1].reason)

    def test_following_every_recommendation_with_regular_failures(self):
        self.follow(60, outcome=lambda step: step % 3 != 0)

    def test_following_every_recommendation_with_mostly_failures(self):
        self.follow(40, outcome=lambda step: step % 4 == 0)

    def test_pick_problem_skips_solved_problems_for_every_activity_except_revision(self):
        for problem in (self.c.easy1, self.c.medium, self.c.tp_easy):
            self.log.add(problem, True)
        solved = {self.c.easy1.pk, self.c.medium.pk, self.c.tp_easy.pk}
        for activity in (Activity.EASIER, Activity.SAME, Activity.HARDER, Activity.RELATED, Activity.NEXT_TOPIC):
            for topic in (self.c.arrays, self.c.strings, self.c.graphs):
                picked = self.engine.pick_problem(self.student, topic, activity, subtopic=self.c.pointers)
                if picked is not None:
                    self.assertNotIn(picked.pk, solved, f"{activity} in {topic}")

    def test_revision_only_offers_solved_problems(self):
        self.log.add(self.c.easy1, True)
        self.log.add(self.c.easy2, False)
        picked = self.engine.pick_problem(self.student, self.c.arrays, Activity.REVISION)
        self.assertEqual(picked, self.c.easy1)

    def test_revision_with_nothing_solved_gives_nothing(self):
        self.assertIsNone(self.engine.pick_problem(self.student, self.c.arrays, Activity.REVISION))

    def test_another_students_solved_problems_do_not_count(self):
        AttemptLog(make_student("other@example.com")).add(self.c.easy1, True)
        self.assertEqual(self.recommend().problem, self.c.easy1)  # new student: still the first problem


# ---------------------------------------------------------------- rule 5 and storage
class SuggestionOnlyTests(EngineTestBase):
    def test_recommending_changes_nothing_about_what_the_student_may_open(self):
        from attempts.models import Attempt

        before = Attempt.objects.count()
        self.recommend()
        self.assertEqual(Attempt.objects.count(), before)  # only a Recommendation row is added
        self.assertEqual(Recommendation.objects.count(), 1)


class StorageTests(EngineTestBase):
    def test_all_activities_and_sources_exist(self):
        self.assertEqual(
            [value for value, _ in Activity.choices],
            ["EASIER", "SAME", "HARDER", "RELATED", "REVISION", "NEXT_TOPIC"],
        )
        self.assertEqual([v for v, _ in Recommendation.Source.choices], ["RULE", "MODEL_ASSISTED"])

    def test_students_only_see_their_own_recommendations(self):
        other = make_student("other@example.com")
        mine = self.recommend()
        theirs = self.recommend(other)
        self.assertEqual(list(Recommendation.objects.for_student(self.student)), [mine])
        self.assertEqual(list(Recommendation.objects.for_student(other)), [theirs])
        self.assertEqual(Recommendation.objects.for_student(None).count(), 0)

    def test_newest_comes_first(self):
        first = self.recommend()
        second = self.recommend()
        self.assertEqual(list(Recommendation.objects.for_student(self.student)), [second, first])

    def test_deleting_a_problem_keeps_the_recommendation(self):
        rec = self.recommend()
        rec.problem.delete()
        rec.refresh_from_db()
        self.assertIsNone(rec.problem)
        self.assertTrue(rec.reason)


# ---------------------------------------------------------------- determinism
class DeterminismTests(EngineTestBase):
    def build_history(self, student):
        log = AttemptLog(student)
        log.many(self.c.easy1, "FC", secs=400)
        log.many(self.c.easy2, "FC", secs=400)
        log.many(self.c.tp_easy, "F", secs=400)

    def as_tuple(self, rec):
        return (rec.activity, rec.problem_id, rec.topic_id, rec.reason, rec.source)

    def test_same_data_gives_the_same_recommendation_every_time(self):
        self.build_history(self.student)
        results = {self.as_tuple(self.recommend()) for _ in range(5)}
        self.assertEqual(len(results), 1)

    def test_two_students_with_the_same_history_get_the_same_recommendation(self):
        twin = make_student("twin@example.com")
        self.build_history(self.student)
        self.build_history(twin)
        self.assertEqual(self.as_tuple(self.recommend()), self.as_tuple(self.recommend(twin)))

    def test_a_new_engine_gives_the_same_answer(self):
        self.build_history(self.student)
        again = RecommendationEngine(clock=lambda: NOW)
        self.assertEqual(self.as_tuple(self.recommend()), self.as_tuple(again.recommend(self.student)))

    def test_candidates_are_listed_in_the_same_order_every_time(self):
        self.build_history(self.student)
        first = [(c.activity, c.topic.pk) for c in self.engine.candidates(self.student)]
        second = [(c.activity, c.topic.pk) for c in self.engine.candidates(self.student)]
        self.assertEqual(first, second)

    def test_only_the_state_of_the_data_matters_not_when_it_was_written(self):
        """The order of the problems is fixed by topic, subtopic, difficulty and id: never random."""
        self.log.many(self.c.hard, "CCC", secs=100)
        picks = [self.engine.pick_problem(self.student, self.c.strings, Activity.NEXT_TOPIC) for _ in range(5)]
        self.assertEqual({p.pk for p in picks}, {self.c.s_easy.pk})


class TieBreakTests(EngineTestBase):
    """When two problems are equally good, the lowest id wins. Never random."""

    def extra_problem(self, title, difficulty, subtopic):
        return Problem.objects.create(title=title, statement="S", difficulty=difficulty, subtopic=subtopic)

    def test_same_level_ties_go_to_the_lowest_id(self):
        easy3 = self.extra_problem("Easy 3", "Easy", self.c.traversal)
        self.log.many(self.c.easy1, "FC", secs=400)  # newest attempts: Easy, in Traversal
        rec = self.recommend()
        self.assert_rec(rec, Activity.SAME, self.c.easy2)  # easy2 and easy3 are equal; easy2 has the lower id
        self.assertLess(self.c.easy2.pk, easy3.pk)

    def test_next_topic_ties_go_to_the_lowest_id(self):
        self.extra_problem("S Easy 2", "Easy", self.c.basics)
        self.log.many(self.c.hard, "CCC", secs=100)
        self.assert_rec(self.recommend(), Activity.NEXT_TOPIC, self.c.s_easy)

    def test_harder_ties_go_to_the_lowest_id(self):
        self.extra_problem("Medium 2", "Medium", self.c.traversal)
        for problem in (self.c.easy1, self.c.easy2, self.c.tp_easy):
            self.log.add(problem, True, secs=100)
        self.assert_rec(self.recommend(), Activity.HARDER, self.c.medium)

    def test_easier_ties_go_to_the_lowest_id(self):
        self.extra_problem("Easy 3", "Easy", self.c.traversal)
        self.log.add(self.c.medium, False)
        self.log.add(self.c.tp_medium, False)
        self.log.add(self.c.medium, False)
        self.assert_rec(self.recommend(), Activity.EASIER, self.c.easy1)

    def test_roadmap_fallback_ties_go_to_the_lowest_id(self):
        self.extra_problem("Easy 3", "Easy", self.c.traversal)
        for problem in (self.c.s_easy, self.c.s_medium, self.c.g_easy, self.c.g_hard):
            self.log.add(problem, True)
        self.assertEqual(self.recommend().problem, self.c.easy1)


class PerformanceTests(EngineTestBase):
    def test_recommendation_is_fast_even_with_many_attempts(self):
        problems = [self.c.easy1, self.c.easy2, self.c.medium, self.c.hard, self.c.tp_easy, self.c.tp_medium]
        for round_number in range(25):
            for problem in problems:
                self.log.add(problem, round_number % 2 == 0, secs=200)
        self.assertEqual(self.student.attempts.count(), 150)
        started = time.perf_counter()
        self.recommend()
        self.assertLess(time.perf_counter() - started, 2)  # the target is under 2 seconds
