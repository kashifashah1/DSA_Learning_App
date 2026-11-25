"""Logic for the problem list and the roadmap pages (views only call these classes)."""

from collections import Counter
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Count, Prefetch

from analytics.services import MasteryCalculator, PerformanceAnalyzer
from attempts.models import Attempt
from problems.models import Problem, Subtopic, Topic
from recommendations.models import Recommendation

NOT_ATTEMPTED = "not_attempted"
ATTEMPTED = "attempted"
SOLVED = "solved"


@dataclass
class ProblemRow:
    """One line of the problem list: the problem and this student's status for it."""

    problem: Problem
    status: str


class ProblemListService:
    """Finds the problems for the list page and marks each one for a student."""

    def get_problems(self, student, topic=None, subtopic=None, difficulty=None):
        problems = Problem.objects.select_related("subtopic__topic")
        if topic:
            problems = problems.filter(subtopic__topic=topic)
        if subtopic:
            problems = problems.filter(subtopic=subtopic)
        if difficulty:
            problems = problems.filter(difficulty=difficulty)

        # Two small queries give the status of every problem (no query per problem).
        mine = Attempt.objects.filter(student=student)
        attempted_ids = set(mine.values_list("problem_id", flat=True))
        solved_ids = set(mine.filter(is_correct=True).values_list("problem_id", flat=True))

        return [ProblemRow(problem, self._status(problem.pk, attempted_ids, solved_ids)) for problem in problems]

    @staticmethod
    def _status(problem_id, attempted_ids, solved_ids):
        if problem_id in solved_ids:
            return SOLVED
        if problem_id in attempted_ids:
            return ATTEMPTED
        return NOT_ATTEMPTED


# ---------------------------------------------------------------------------
@dataclass
class RoadmapSubtopic:
    subtopic: Subtopic
    problem_count: int
    solved_count: int


@dataclass
class RoadmapTopic:
    topic: Topic
    level: str  # Beginner / Intermediate / Advanced, or "Not enough data"
    mastery: float | None  # the score behind the level (None if not enough data)
    attempts: int  # the student's attempts in this topic
    attempts_needed: int  # how many more attempts are needed before a level can be shown
    subtopics: list = field(default_factory=list)


class RoadmapService:
    """Builds the roadmap: topics and subtopics in order, with the student's real mastery level."""

    NOT_ENOUGH_DATA = "Not enough data"

    def __init__(self, analyzer=None, mastery=None):
        self.analyzer = analyzer or PerformanceAnalyzer()
        self.mastery = mastery or MasteryCalculator()

    def get_roadmap(self, student):
        # order_by is written out because Django ignores a model's default ordering
        # in queries that use Count (GROUP BY).
        subtopics = Subtopic.objects.annotate(problem_count=Count("problems")).order_by("order", "name")
        topics = Topic.objects.prefetch_related(Prefetch("subtopics", queryset=subtopics))

        stats_by_topic = self.analyzer.all_topic_stats(student)  # one pass over the student's attempts
        solved_ids = set(
            Attempt.objects.for_student(student).filter(is_correct=True).values_list("problem_id", flat=True)
        )
        solved_by_subtopic = Counter(
            Problem.objects.filter(pk__in=solved_ids).values_list("subtopic_id", flat=True)
        )

        roadmap = []
        for topic in topics:
            stats = stats_by_topic.get(topic.pk)
            score = self.mastery.mastery_score(stats) if stats else None
            attempts = stats.total_attempts if stats else 0
            item = RoadmapTopic(
                topic=topic,
                level=self.mastery.learning_level(score),
                mastery=score,
                attempts=attempts,
                attempts_needed=0 if score is not None else max(settings.MIN_ATTEMPTS_PER_TOPIC - attempts, 0),
            )
            for subtopic in topic.subtopics.all():
                item.subtopics.append(
                    RoadmapSubtopic(
                        subtopic=subtopic,
                        problem_count=subtopic.problem_count,
                        solved_count=solved_by_subtopic.get(subtopic.pk, 0),
                    )
                )
            roadmap.append(item)
        return roadmap


# ---------------------------------------------------------------------------
@dataclass
class DashboardData:
    total_problems: int
    solved_count: int  # different problems solved
    tried_count: int  # different problems tried
    attempts_count: int
    recent_attempts: list
    recommendation: Recommendation | None
    overall_skill: float | None = None  # 0 to 100, None until a topic has enough data
    overall_level: str = "Not enough data"
    strong_topics: list = field(default_factory=list)  # TopicPerformance rows, strongest first
    weak_topics: list = field(default_factory=list)  # TopicPerformance rows, weakest first

    @property
    def has_attempts(self):
        return self.attempts_count > 0


class DashboardService:
    """Everything the dashboard shows, from the student's own real data (nothing is made up)."""

    RECENT = 5

    def __init__(self, analyzer=None, mastery=None):
        self.analyzer = analyzer or PerformanceAnalyzer()
        self.mastery = mastery or MasteryCalculator()

    def get(self, student):
        attempts = Attempt.objects.for_student(student)
        skill = self.analyzer.overall_skill(student)
        return DashboardData(
            overall_skill=skill,
            overall_level=self.mastery.learning_level(skill),
            strong_topics=self.analyzer.strong_topics(student),
            weak_topics=self.analyzer.weak_topics(student),
            total_problems=Problem.objects.count(),
            solved_count=attempts.filter(is_correct=True).values("problem_id").distinct().count(),
            tried_count=attempts.values("problem_id").distinct().count(),
            attempts_count=attempts.count(),
            recent_attempts=list(attempts.select_related("problem").order_by("-submitted_at", "-id")[: self.RECENT]),
            recommendation=Recommendation.objects.for_student(student).select_related("problem", "topic").first(),
        )


# ---------------------------------------------------------------------------
class ChartDataService:
    """The numbers behind the three analytics charts. Always only the given student's own data.
    Accuracy values are percentages (0 to 100); a value of None means "no data" (the chart skips it)."""

    def __init__(self, analyzer=None, mastery=None):
        self.analyzer = analyzer or PerformanceAnalyzer()
        self.mastery = mastery or MasteryCalculator()

    @staticmethod
    def _percent(value):
        return None if value is None else round(value * 100, 1)

    def has_attempts(self, student):
        return Attempt.objects.for_student(student).exists()

    def trend(self, student):
        """Accuracy over time: one point per day with attempts."""
        return [
            {
                "date": row["date"],
                "attempts": row["attempts"],
                "daily_accuracy": self._percent(row["daily_accuracy"]),
                "cumulative_accuracy": self._percent(row["cumulative_accuracy"]),
            }
            for row in self.analyzer.accuracy_trend(student)
        ]

    def topics(self, student):
        """Topic-wise performance in roadmap order (only topics the student has attempted)."""
        stats_by_topic = self.analyzer.all_topic_stats(student)
        result = []
        for stats in sorted(stats_by_topic.values(), key=lambda s: (s.topic.order, s.topic.pk)):
            score = self.mastery.mastery_score(stats)
            result.append(
                {
                    "topic": stats.topic.name,
                    "attempts": stats.total_attempts,
                    "accuracy": self._percent(stats.accuracy),
                    "recent_accuracy": self._percent(stats.recent_accuracy),
                    "mastery": score,
                    "level": self.mastery.learning_level(score),
                }
            )
        return result

    def difficulty(self, student):
        """Accuracy for Easy, Medium and Hard problems."""
        return [
            {
                "difficulty": row["difficulty"],
                "attempts": row["attempts"],
                "correct": row["correct"],
                "accuracy": self._percent(row["accuracy"]),
            }
            for row in self.analyzer.difficulty_accuracy(student)
        ]
