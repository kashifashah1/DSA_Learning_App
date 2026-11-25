"""Performance statistics and mastery.

PerformanceAnalyzer calculates everything from a student's attempts (Pandas + NumPy) and
keeps the stored TopicPerformance row of a topic up to date. MasteryCalculator turns the
numbers into a mastery score and a learning level.

Same attempts always give the same numbers: attempts are always read in the order
(submitted_at, id), and all settings come from the RuleConfig in settings.py.
"""

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from django.conf import settings

from attempts.models import Attempt
from problems.models import Subtopic, Topic

from .models import TopicPerformance

NOT_ENOUGH_DATA = "Not enough data"

# The inputs of the success model, always in this order (training and predicting use the same list).
FEATURE_COLUMNS = ["topic_mastery", "recent_accuracy", "avg_time_sec", "difficulty"]
DIFFICULTY_CODE = {"Easy": 0, "Medium": 1, "Hard": 2}  # problem difficulty as a number
DIFFICULTIES = ["Easy", "Medium", "Hard"]  # in this order on every page and chart


@dataclass(frozen=True)
class TopicStats:
    """The numbers about one student in one topic (all attempts of that student in the topic)."""

    topic: Topic
    total_attempts: int
    correct_attempts: int
    accuracy: float  # correct attempts / all attempts
    recent_accuracy: float  # the same for the last RECENT_WINDOW attempts
    baseline_accuracy: float | None  # accuracy BEFORE the recent attempts (None if too few older attempts)
    avg_time_sec: float  # average time taken per attempt
    avg_attempts: float  # average number of attempts per problem tried
    speed_score: float  # 0 to 1: how fast the correct attempts were, compared to the expected time
    efficiency_score: float  # 0 to 1: solving a problem on the first try is 1, on the second try 0.5, ...
    last_practised: datetime


@dataclass(frozen=True)
class SubtopicAccuracy:
    subtopic: Subtopic
    attempts: int
    accuracy: float


class PerformanceAnalyzer:
    """Calculates performance numbers from a student's attempts (always only that student's)."""

    def __init__(self, mastery=None):
        self.mastery = mastery or MasteryCalculator()

    def all_topic_stats(self, student):
        """{topic id: TopicStats} for every topic the student has attempted."""
        by_topic = {}
        for attempt in self._attempts(student):
            by_topic.setdefault(attempt.problem.subtopic.topic, []).append(attempt)
        return {topic.pk: self._stats(topic, attempts) for topic, attempts in by_topic.items()}

    def topic_stats(self, student, topic):
        """TopicStats for one topic, or None if the student has no attempts in it."""
        attempts = list(self._attempts(student, topic))
        return self._stats(topic, attempts) if attempts else None

    def recent_attempts(self, student, topic):
        """The last RECENT_WINDOW attempts in the topic, newest first."""
        attempts = list(self._attempts(student, topic))
        return list(reversed(attempts[-settings.RECENT_WINDOW:]))

    def latest_attempt(self, student):
        """The student's newest attempt in any topic, or None."""
        return self._attempts(student).last()

    def subtopic_accuracy(self, student, topic):
        """Accuracy per subtopic (only subtopics with attempts), in roadmap order."""
        by_subtopic = {}
        for attempt in self._attempts(student, topic):
            by_subtopic.setdefault(attempt.problem.subtopic, []).append(attempt)
        rows = [
            SubtopicAccuracy(subtopic, len(attempts), sum(a.is_correct for a in attempts) / len(attempts))
            for subtopic, attempts in by_subtopic.items()
        ]
        return sorted(rows, key=lambda row: (row.subtopic.order, row.subtopic.pk))


    # ------------------------------------------------------------------ Pandas views of the attempts
    def attempts_dataframe(self, student, topic=None):
        """The student's attempts (optionally of one topic) as a Pandas DataFrame, oldest first."""
        rows = [
            {
                "attempt_id": a.pk,
                "problem_id": a.problem_id,
                "topic_id": a.problem.subtopic.topic_id,
                "topic": a.problem.subtopic.topic.name,
                "difficulty": a.difficulty,
                "is_correct": bool(a.is_correct),
                "attempt_no": a.attempt_no,
                "time_taken_sec": a.time_taken_sec,
                "submitted_at": a.submitted_at,
            }
            for a in self._attempts(student, topic)
        ]
        columns = [
            "attempt_id", "problem_id", "topic_id", "topic", "difficulty",
            "is_correct", "attempt_no", "time_taken_sec", "submitted_at",
        ]
        return pd.DataFrame(rows, columns=columns)

    def difficulty_accuracy(self, student, topic=None):
        """Accuracy per difficulty: [{difficulty, attempts, correct, accuracy}] for Easy, Medium, Hard.
        accuracy is None when the student has no attempt of that difficulty."""
        df = self.attempts_dataframe(student, topic)
        result = []
        for difficulty in DIFFICULTIES:
            part = df[df["difficulty"] == difficulty]
            attempts = int(len(part))
            correct = int(part["is_correct"].sum()) if attempts else 0
            accuracy = float(np.round(correct / attempts, 4)) if attempts else None
            result.append({"difficulty": difficulty, "attempts": attempts, "correct": correct, "accuracy": accuracy})
        return result

    def accuracy_trend(self, student):
        """Accuracy over time, one row per day with attempts (oldest first):
        [{date, attempts, daily_accuracy, cumulative_accuracy}]. Days follow settings.TIME_ZONE."""
        df = self.attempts_dataframe(student)
        if df.empty:
            return []
        local_time = pd.to_datetime(df["submitted_at"], utc=True).dt.tz_convert(settings.TIME_ZONE)
        df = df.assign(day=local_time.dt.date, correct=df["is_correct"].astype(int))
        per_day = df.groupby("day").agg(attempts=("correct", "size"), correct=("correct", "sum")).sort_index()
        per_day["daily_accuracy"] = per_day["correct"] / per_day["attempts"]
        per_day["cumulative_accuracy"] = per_day["correct"].cumsum() / per_day["attempts"].cumsum()
        return [
            {
                "date": day.isoformat(),
                "attempts": int(row.attempts),
                "daily_accuracy": round(float(row.daily_accuracy), 4),
                "cumulative_accuracy": round(float(row.cumulative_accuracy), 4),
            }
            for day, row in per_day.iterrows()
        ]

    # ------------------------------------------------------------------ stored topic performance
    def update_topic_performance(self, student, topic):
        """Recalculate ONLY this student's numbers in this topic and save them.
        Returns the TopicPerformance row (None, and no row, if the student has no attempt in the topic)."""
        stats = self.topic_stats(student, topic)
        if stats is None:
            TopicPerformance.objects.filter(student=student, topic=topic).delete()
            return None
        return self._store(student, stats)

    def sync_student(self, student):
        """Rebuild the stored rows of every topic the student has attempted (one pass over the attempts)."""
        stats_by_topic = self.all_topic_stats(student)
        TopicPerformance.objects.filter(student=student).exclude(topic_id__in=stats_by_topic.keys()).delete()
        return [self._store(student, stats) for stats in stats_by_topic.values()]

    def overall_skill(self, student):
        """Overall skill score (0 to 100): the average mastery of the topics that have enough data.
        None if no topic has enough data yet. Calculated from the attempts, not stored."""
        scores = [self.mastery.mastery_score(stats) for stats in self.all_topic_stats(student).values()]
        scores = [score for score in scores if score is not None]
        return round(float(np.mean(scores)), 2) if scores else None

    def weak_topics(self, student, limit=3):
        """The topics with the lowest mastery (only topics with enough data), weakest first.
        A topic is never both weak and strong, and an Advanced topic is never weak."""
        ranked = self._ranked_rows(student)
        strong = self._strong_rows(ranked, limit)
        half = ranked[::-1][: math.ceil(len(ranked) / 2)]  # the lower half (weakest first)
        ceiling = settings.LEVEL_RANGES["ADVANCED_ABOVE"]
        return [row for row in half if row.mastery_score <= ceiling and row not in strong][:limit]

    def strong_topics(self, student, limit=3):
        """The topics with the highest mastery (only topics with enough data), strongest first.
        A Beginner topic is never strong."""
        return self._strong_rows(self._ranked_rows(student), limit)

    def _strong_rows(self, ranked, limit):
        upper = ranked[: math.ceil(len(ranked) / 2)]
        floor = settings.LEVEL_RANGES["BEGINNER_BELOW"]
        return [row for row in upper if row.mastery_score >= floor][:limit]

    def _ranked_rows(self, student):
        """Stored rows with a mastery score, strongest first (ties: roadmap order, then id)."""
        rows = TopicPerformance.objects.filter(student=student, mastery_score__isnull=False).select_related("topic")
        if not rows.exists() and Attempt.objects.for_student(student).exists():
            self.sync_student(student)  # rows are missing (older data): build them once
            rows = TopicPerformance.objects.filter(student=student, mastery_score__isnull=False).select_related("topic")
        return sorted(rows, key=lambda row: (-row.mastery_score, row.topic.order, row.topic_id))

    def _store(self, student, stats):
        score = self.mastery.mastery_score(stats)
        row, _ = TopicPerformance.objects.update_or_create(
            student=student,
            topic=stats.topic,
            defaults={
                "total_attempts": stats.total_attempts,
                "accuracy": stats.accuracy,
                "recent_accuracy": stats.recent_accuracy,
                "avg_time_sec": stats.avg_time_sec,
                "avg_attempts": stats.avg_attempts,
                "mastery_score": score,
                "learning_level": self.mastery.learning_level(score),
                "last_practised": stats.last_practised,
            },
        )
        return row

    # ------------------------------------------------------------------ machine learning
    def prediction_features(self, stats, difficulty):
        """The model's inputs for "this student tries a problem of this difficulty NOW".
        stats: the TopicStats of the problem's topic, or None if the student never tried the topic."""
        return self._feature_row(stats, difficulty)

    def build_training_data(self):
        """One row for every stored attempt of every student, for training the success model.

        The features describe what was known BEFORE that attempt (only the student's earlier
        attempts in the same topic): topic mastery, recent accuracy, average solving time and
        the problem difficulty. The label `solved` is 1 if the attempt was correct, else 0.
        Missing values (no or too few earlier attempts) are NaN; the model fills them in.
        """
        attempts = Attempt.objects.select_related("problem__subtopic__topic").order_by(
            "student_id", "submitted_at", "id"
        )
        earlier_by_group = {}  # (student, topic) -> the attempts seen so far, oldest first
        rows = []
        for attempt in attempts:
            topic = attempt.problem.subtopic.topic
            earlier = earlier_by_group.setdefault((attempt.student_id, topic.pk), [])
            stats = self._stats(topic, earlier) if earlier else None
            row = {"attempt_id": attempt.pk, "student_id": attempt.student_id}
            row.update(self._feature_row(stats, attempt.difficulty))
            row["solved"] = int(attempt.is_correct)
            rows.append(row)
            earlier.append(attempt)  # only AFTER the row is made: an attempt never sees itself
        columns = ["attempt_id", "student_id", *FEATURE_COLUMNS, "solved"]
        return pd.DataFrame(rows, columns=columns)

    def _feature_row(self, stats, difficulty):
        nan = math.nan
        if stats is None:
            mastery = recent = avg_time = nan
        else:
            score = self.mastery.mastery_score(stats)
            mastery = nan if score is None else score
            recent, avg_time = stats.recent_accuracy, stats.avg_time_sec
        return {
            "topic_mastery": mastery,
            "recent_accuracy": recent,
            "avg_time_sec": avg_time,
            "difficulty": DIFFICULTY_CODE[difficulty],
        }

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _attempts(student, topic=None):
        attempts = Attempt.objects.for_student(student).select_related("problem__subtopic__topic")
        if topic is not None:
            attempts = attempts.filter(problem__subtopic__topic=topic)
        return attempts.order_by("submitted_at", "id")

    @staticmethod
    def _stats(topic, attempts):
        """attempts: the student's attempts in this topic, oldest first (never empty)."""
        recent = attempts[-settings.RECENT_WINDOW:]
        older = attempts[: len(attempts) - len(recent)]

        def accuracy(rows):
            return sum(a.is_correct for a in rows) / len(rows)

        # Speed: only correct attempts count. 1.0 means "as fast as expected or faster".
        correct = [a for a in attempts if a.is_correct]
        speeds = [min(1.0, settings.EXPECTED_SOLVE_SEC[a.difficulty] / max(a.time_taken_sec, 1)) for a in correct]

        # Per problem: how many tries did it take to get the first correct attempt?
        per_problem = {}
        for attempt in attempts:
            per_problem.setdefault(attempt.problem_id, []).append(attempt)
        efficiencies = []
        for tries in per_problem.values():
            first_correct = next((a for a in tries if a.is_correct), None)
            if first_correct:
                efficiencies.append(1 / first_correct.attempt_no)

        return TopicStats(
            topic=topic,
            total_attempts=len(attempts),
            correct_attempts=len(correct),
            accuracy=accuracy(attempts),
            recent_accuracy=accuracy(recent),
            baseline_accuracy=accuracy(older) if len(older) >= settings.MIN_ATTEMPTS_PER_TOPIC else None,
            avg_time_sec=sum(a.time_taken_sec for a in attempts) / len(attempts),
            avg_attempts=len(attempts) / len(per_problem),
            speed_score=sum(speeds) / len(speeds) if speeds else 0.0,
            efficiency_score=sum(efficiencies) / len(efficiencies) if efficiencies else 0.0,
            last_practised=attempts[-1].submitted_at,
        )


class MasteryCalculator:
    """Turns TopicStats into a mastery score (0 to 100) and a learning level."""

    def mastery_score(self, stats):
        """Weighted sum of accuracy, recent accuracy, speed and attempt efficiency.
        None if the student has too few attempts in the topic (MIN_ATTEMPTS_PER_TOPIC)."""
        if stats.total_attempts < settings.MIN_ATTEMPTS_PER_TOPIC:
            return None
        weights = settings.MASTERY_WEIGHTS
        score = 100 * (
            weights["accuracy"] * stats.accuracy
            + weights["recent_accuracy"] * stats.recent_accuracy
            + weights["speed"] * stats.speed_score
            + weights["attempt_efficiency"] * stats.efficiency_score
        )
        return round(score, 2)

    def learning_level(self, score):
        """Beginner (below 40), Intermediate (40 to 70), Advanced (above 70)."""
        if score is None:
            return NOT_ENOUGH_DATA
        ranges = settings.LEVEL_RANGES
        if score < ranges["BEGINNER_BELOW"]:
            return "Beginner"
        if score <= ranges["ADVANCED_ABOVE"]:
            return "Intermediate"
        return "Advanced"
