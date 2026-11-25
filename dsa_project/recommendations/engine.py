"""RecommendationEngine: suggests the next activity using RULES only (no model yet).

recommend(student) works in this order:
  1. New student (no attempts)  -> the easiest problem of the first topic.
  2. Revision                   -> a topic that was strong but is slipping or forgotten.
  3. Difficulty adjustment      -> looking at the recent attempts in the topic the student
                                   practised last, in this order: EASIER (repeated failures),
                                   HARDER (several correct and fast), NEXT_TOPIC (mastery high,
                                   used when no harder problem is left), RELATED (weakest subtopic),
                                   SAME (steady results). If the level is used up, the topic goes on
                                   one level up (or down) before the next topic starts.
  4. A problem the student already solved is never suggested, except for REVISION.
  5. It is only a suggestion: nothing stops the student from opening any problem.
  6. Hybrid: if a trained model is available, it ranks the candidate problems of the chosen
     activity and the one whose predicted chance of success is closest to TARGET_SUCCESS_PROB
     is suggested (source MODEL_ASSISTED). Without a usable model the rules above decide on
     their own (source RULE); the student never sees an error.

Every number used in a rule comes from settings.py (RuleConfig). The same attempts always
give the same recommendation: candidate problems are always sorted in a fixed order.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from analytics.ml import SuccessPredictor
from analytics.services import MasteryCalculator, PerformanceAnalyzer
from attempts.models import Attempt
from problems.models import Problem, Subtopic, Topic

from .models import Recommendation

logger = logging.getLogger(__name__)
Activity = Recommendation.Activity

DIFFICULTY_RANK = {"Easy": 0, "Medium": 1, "Hard": 2}
RANK_NAME = {rank: name for name, rank in DIFFICULTY_RANK.items()}


@dataclass
class Choice:
    """A decision before a problem is picked: what to do, in which topic, and why."""

    activity: str
    topic: Topic
    reason: str
    subtopic: Subtopic | None = None  # only for RELATED practice
    use_model: bool = True  # False for rules that name the exact problem (new student, revision)


@dataclass
class ModelPick:
    """The problem chosen by the model and its predicted chance of success (0 to 1)."""

    problem: Problem
    probability: float


class RecommendationEngine:
    def __init__(self, analyzer=None, mastery=None, clock=None, predictor=None):
        self.analyzer = analyzer or PerformanceAnalyzer()
        self.mastery = mastery or MasteryCalculator()
        self.clock = clock or timezone.now
        self.predictor = predictor or SuccessPredictor()

    # ------------------------------------------------------------------ main API
    def recommend(self, student):
        """Decide, store and return the next Recommendation for the student."""
        model_ready = None  # asked only when needed, and only once
        for choice in self.candidates(student):
            options = self.candidate_problems(student, choice.topic, choice.activity, choice.subtopic)
            if not options:
                continue

            problem, source, reason = options[0], Recommendation.Source.RULE, choice.reason
            if choice.use_model and len(options) > 1:  # with one candidate there is nothing to rank
                if model_ready is None:
                    model_ready = self._model_ready()
                pick = self.rank_with_model(student, options) if model_ready else None
                if pick is not None:
                    problem, source = pick.problem, Recommendation.Source.MODEL_ASSISTED
                    reason += (
                        f" Our model estimates about a {pick.probability:.0%} chance that you solve it "
                        f"(the target is {settings.TARGET_SUCCESS_PROB:.0%})."
                    )
            return self._store(student, choice.activity, choice.topic, problem, reason, source)
        return self._last_resort(student)

    def rank_with_model(self, student, problems):
        """Among the candidate problems (already in the fixed rule order), the one whose predicted
        chance of success is closest to TARGET_SUCCESS_PROB. Equal distances keep the rule order.
        Returns a ModelPick, or None if the model cannot be used (the rules then decide)."""
        try:
            stats_by_topic = {}
            scored = []
            for position, problem in enumerate(problems):
                topic = problem.subtopic.topic
                if topic.pk not in stats_by_topic:
                    stats_by_topic[topic.pk] = self.analyzer.topic_stats(student, topic)
                features = self.analyzer.prediction_features(stats_by_topic[topic.pk], problem.difficulty)
                probability = self.predictor.predict_probability(features)
                distance = round(abs(probability - settings.TARGET_SUCCESS_PROB), 9)
                scored.append((distance, position, problem, probability))
            _, _, problem, probability = min(scored, key=lambda item: (item[0], item[1]))
            return ModelPick(problem, probability)
        except Exception:
            # Never an error for the student: log it and let the rules decide.
            logger.warning("The model could not rank the problems: using the rules instead", exc_info=True)
            return None

    def _model_ready(self):
        try:
            return bool(self.predictor.is_available())
        except Exception:
            logger.warning("Could not check the model: using the rules instead", exc_info=True)
            return False

    def choose_activity(self, student):
        """The first (most important) choice for this student, or None."""
        choices = self.candidates(student)
        return choices[0] if choices else None

    def candidates(self, student):
        """All choices in order of importance. The first one that has a problem to offer is used."""
        topics = list(Topic.objects.all())  # roadmap order
        stats_by_topic = self.analyzer.all_topic_stats(student)
        solved = self._solved_ids(student)

        # Rule 1: a new student starts with the first topic.
        if not stats_by_topic:
            return self._first_topic_choice(topics)

        choices = []
        now = self.clock()

        # Rule 2: revision (the first topic in roadmap order that needs it).
        for topic in topics:
            stats = stats_by_topic.get(topic.pk)
            if stats and self.needs_revision(stats, now):
                choices.append(Choice(Activity.REVISION, topic, self._revision_reason(stats, now), use_model=False))
                break

        # Rule 3: adjust the difficulty from the recent attempts in the topic practised last.
        latest = self.analyzer.latest_attempt(student)
        topic = latest.problem.subtopic.topic
        stats = stats_by_topic[topic.pk]
        next_topic = self._next_topic_with_unsolved(topic, topics, solved)

        if stats.total_attempts >= settings.MIN_ATTEMPTS_PER_TOPIC:
            recent = self.analyzer.recent_attempts(student, topic)  # newest first
            failures = sum(1 for a in recent if not a.is_correct)
            fast_correct = sum(1 for a in recent if self._is_fast_and_correct(a))
            mastery = self.mastery.mastery_score(stats)

            if not recent[0].is_correct and failures >= settings.EASIER_MIN_FAILURES:
                choices.append(Choice(
                    Activity.EASIER, topic,
                    f"{failures} of your last {len(recent)} attempts in {topic.name} did not pass, "
                    f"so here is an easier problem to rebuild your confidence.",
                ))
            if recent[0].is_correct and fast_correct >= settings.HARDER_MIN_CORRECT:
                choices.append(Choice(
                    Activity.HARDER, topic,
                    f"You solved {fast_correct} of your last {len(recent)} attempts in {topic.name} "
                    f"correctly and quickly, so here is a harder problem.",
                ))
            if mastery is not None and mastery > settings.LEVEL_RANGES["ADVANCED_ABOVE"] and next_topic:
                choices.append(Choice(
                    Activity.NEXT_TOPIC, next_topic,
                    f"Your mastery of {topic.name} is high ({mastery:.0f} out of 100), "
                    f"so it is time to start the next topic: {next_topic.name}.",
                ))

            weakest = self._weakest_subtopic(student, topic, stats)
            if weakest:
                choices.append(Choice(
                    Activity.RELATED, topic,
                    f"Your accuracy in {weakest.subtopic.name} ({weakest.accuracy:.0%}) is lower than "
                    f"in the rest of {topic.name} ({stats.accuracy:.0%}), so here is more practice there.",
                    subtopic=weakest.subtopic,
                ))

        choices.append(Choice(
            Activity.SAME, topic,
            f"Your results in {topic.name} are steady, so here is another problem at the same level.",
        ))
        # Nothing left at this level? Stay in the topic and move one level (up first, then down)
        # before jumping to another topic.
        level = latest.difficulty
        choices.append(Choice(
            Activity.HARDER, topic,
            f"You have finished the {level} problems in {topic.name}, so here is a harder one.",
        ))
        choices.append(Choice(
            Activity.EASIER, topic,
            f"There are no more {level} problems left in {topic.name}, so here is an easier one you have not solved yet.",
        ))
        if next_topic:
            choices.append(Choice(
                Activity.NEXT_TOPIC, next_topic,
                f"There are no more problems to practise at this level in {topic.name}, "
                f"so here is the next topic: {next_topic.name}.",
            ))
        return choices

    def needs_revision(self, stats, now):
        """True if the topic was strong and either recent accuracy dropped or it was not practised for long."""
        if stats.total_attempts < settings.MIN_ATTEMPTS_PER_TOPIC:
            return False
        if self._dropped(stats):
            return True
        stale = now - stats.last_practised > timedelta(days=settings.REVISION_AFTER_DAYS)
        return stale and stats.accuracy >= settings.STRONG_TOPIC_ACCURACY

    def pick_problem(self, student, topic, activity, subtopic=None):
        """The first suitable problem in a FIXED order (the rules' choice), or None."""
        options = self.candidate_problems(student, topic, activity, subtopic)
        return options[0] if options else None

    def candidate_problems(self, student, topic, activity, subtopic=None):
        """All suitable problems in a FIXED order (never random). Solved problems are left out,
        except for REVISION, which only offers solved ones."""
        solved = self._solved_ids(student)
        attempted = set(Attempt.objects.for_student(student).values_list("problem_id", flat=True))
        problems = list(Problem.objects.filter(subtopic__topic=topic).select_related("subtopic__topic"))

        if activity == Activity.REVISION:
            return self._solved_in_order(student, problems)

        unsolved = [p for p in problems if p.pk not in solved]
        latest = next(iter(self.analyzer.recent_attempts(student, topic)), None)
        last_rank = DIFFICULTY_RANK[latest.difficulty] if latest else 0
        last_subtopic_id = latest.problem.subtopic_id if latest else None
        tried = lambda p: p.pk in attempted  # never-tried problems come before tried-but-unsolved ones

        if activity == Activity.NEXT_TOPIC:  # easiest first
            key = lambda p: (DIFFICULTY_RANK[p.difficulty], p.subtopic.order, p.subtopic_id, p.pk)
            candidates = unsolved
        elif activity == Activity.HARDER:  # the nearest harder level first
            key = lambda p: (DIFFICULTY_RANK[p.difficulty], tried(p), p.subtopic.order, p.subtopic_id, p.pk)
            candidates = [p for p in unsolved if DIFFICULTY_RANK[p.difficulty] > last_rank]
        elif activity == Activity.EASIER:  # the nearest easier level first
            key = lambda p: (-DIFFICULTY_RANK[p.difficulty], tried(p), p.subtopic.order, p.subtopic_id, p.pk)
            candidates = [p for p in unsolved if DIFFICULTY_RANK[p.difficulty] < last_rank]
        elif activity == Activity.RELATED:  # easiest first, inside the weakest subtopic
            if subtopic is None:
                weak = self._weakest_subtopic(student, topic, self.analyzer.topic_stats(student, topic))
                subtopic = weak.subtopic if weak else None
            key = lambda p: (DIFFICULTY_RANK[p.difficulty], tried(p), p.pk)
            candidates = [p for p in unsolved if subtopic and p.subtopic_id == subtopic.pk]
        else:  # SAME: same level, preferably in the same subtopic
            key = lambda p: (p.subtopic_id != last_subtopic_id, tried(p), p.subtopic.order, p.subtopic_id, p.pk)
            candidates = [p for p in unsolved if DIFFICULTY_RANK[p.difficulty] == last_rank]

        return sorted(candidates, key=key)

    # --------------------------------------------------------------------- rules
    def _dropped(self, stats):
        """Was strong before, but the recent accuracy fell by at least REVISION_ACCURACY_DROP?"""
        if stats.baseline_accuracy is None or stats.baseline_accuracy < settings.STRONG_TOPIC_ACCURACY:
            return False
        # rounded, so that a drop of exactly 0.20 is not missed because of decimal rounding
        return round(stats.baseline_accuracy - stats.recent_accuracy, 6) >= settings.REVISION_ACCURACY_DROP

    def _revision_reason(self, stats, now):
        if self._dropped(stats):
            return (
                f"{stats.topic.name} was going well ({stats.baseline_accuracy:.0%} correct), but your recent "
                f"accuracy fell to {stats.recent_accuracy:.0%}. A quick revision will help."
            )
        return (
            f"You have not practised {stats.topic.name} for over {settings.REVISION_AFTER_DAYS} days. "
            f"Revise a problem you solved before."
        )

    @staticmethod
    def _is_fast_and_correct(attempt):
        return attempt.is_correct and attempt.time_taken_sec <= settings.EXPECTED_SOLVE_SEC[attempt.difficulty]

    def _weakest_subtopic(self, student, topic, stats):
        """The subtopic with the lowest accuracy, if it is lower than the accuracy of the whole topic."""
        rows = self.analyzer.subtopic_accuracy(student, topic)
        if not rows or stats is None:
            return None
        weakest = min(rows, key=lambda row: (row.accuracy, row.subtopic.order, row.subtopic.pk))
        return weakest if weakest.accuracy < stats.accuracy else None

    # ------------------------------------------------------------------- helpers
    @staticmethod
    def _solved_ids(student):
        return set(
            Attempt.objects.for_student(student).filter(is_correct=True).values_list("problem_id", flat=True)
        )

    @staticmethod
    def _next_topic_with_unsolved(current, topics, solved):
        """The first topic after the current one (roadmap order) that still has an unsolved problem."""
        later = [t for t in topics if (t.order, t.name) > (current.order, current.name)]
        for topic in later:
            if Problem.objects.filter(subtopic__topic=topic).exclude(pk__in=solved).exists():
                return topic
        return None

    def _first_topic_choice(self, topics):
        for topic in topics:
            if Problem.objects.filter(subtopic__topic=topic).exists():
                return [Choice(
                    Activity.NEXT_TOPIC, topic,
                    f"Welcome! You are new here, so we start with the easiest problem of the first topic, {topic.name}.",
                    use_model=False,
                )]
        return []

    def _solved_in_order(self, student, problems):
        """For REVISION: the solved problems, the one solved the longest time ago first."""
        solved_at = {}
        correct = Attempt.objects.for_student(student).filter(is_correct=True).order_by("submitted_at", "id")
        for attempt in correct:
            solved_at[attempt.problem_id] = attempt.submitted_at  # the latest correct attempt wins
        options = [p for p in problems if p.pk in solved_at]
        return sorted(options, key=lambda p: (solved_at[p.pk], p.pk))

    def _oldest_solved(self, student, problems):
        options = self._solved_in_order(student, problems)
        return options[0] if options else None

    def _last_resort(self, student):
        """Nothing above gave a problem: take the first unsolved problem in roadmap order,
        or revise the oldest solved one, or say that there are no problems."""
        solved = self._solved_ids(student)
        order = lambda p: (p.subtopic.topic.order, p.subtopic.topic.name, p.subtopic.order, p.subtopic_id,
                           DIFFICULTY_RANK[p.difficulty], p.pk)
        problems = list(Problem.objects.select_related("subtopic__topic"))
        unsolved = [p for p in problems if p.pk not in solved]
        if unsolved:
            problem = min(unsolved, key=order)
            topic = problem.subtopic.topic
            activity = self._fallback_activity(student, problem)
            return self._store(student, activity, topic, problem,
                               f"Here is the next problem you have not solved yet in your roadmap, in {topic.name}.")
        problem = self._oldest_solved(student, problems)
        if problem:
            return self._store(student, Activity.REVISION, problem.subtopic.topic, problem,
                               "You have solved every problem so far. Revise one you solved a while ago.")
        return self._store(student, Activity.NEXT_TOPIC, None, None, "There are no problems available yet.")

    def _fallback_activity(self, student, problem):
        """Name the activity honestly: another topic, or a harder / easier / same-level problem."""
        latest = self.analyzer.latest_attempt(student)
        if latest is None or latest.problem.subtopic.topic_id != problem.subtopic.topic_id:
            return Activity.NEXT_TOPIC
        difference = DIFFICULTY_RANK[problem.difficulty] - DIFFICULTY_RANK[latest.difficulty]
        if difference > 0:
            return Activity.HARDER
        return Activity.EASIER if difference < 0 else Activity.SAME

    @staticmethod
    def _store(student, activity, topic, problem, reason, source=Recommendation.Source.RULE):
        return Recommendation.objects.create(
            student=student, activity=activity, topic=topic, problem=problem,
            reason=reason, source=source,
        )
