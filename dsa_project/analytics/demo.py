"""DEVELOPMENT ONLY: fake students and attempts, so the model can be trained and tested.

Everything made here is clearly marked as fake and must never be shown or described as real data:
  - the e-mail ends with @demo.invalid (such addresses cannot exist) and nobody can log in,
  - the name starts with "DEMO" and ends with "(fake)",
  - the source code of every attempt says it is demo data.
The numbers come from a simple made-up formula (a hidden "skill" per student), not from real people.
"""

import math
import random
from datetime import timedelta

from django.utils import timezone

from analytics.services import PerformanceAnalyzer
from attempts.models import Attempt
from problems.models import Problem
from users.models import User

DEMO_DOMAIN = "demo.invalid"
DEMO_SOURCE_CODE = "# DEMO DATA: a fake attempt made by generate_demo_attempts, not by a real student."

_DIFFICULTY_PENALTY = {"Easy": 0.0, "Medium": 1.0, "Hard": 2.0}
_BASE_TIME_SEC = {"Easy": 240, "Medium": 540, "Hard": 1100}


def demo_students():
    return User.objects.filter(email__endswith="@" + DEMO_DOMAIN)


def demo_attempts():
    return Attempt.objects.filter(student__email__endswith="@" + DEMO_DOMAIN)


def clear_demo_data():
    """Delete all demo students. Their attempts go with them. Real students are never touched."""
    count = demo_students().count()
    demo_students().delete()
    return count


def generate_demo_data(students=40, attempts_per_student=15, seed=42, now=None):
    """Create fake students with fake attempts. The same seed always gives the same data."""
    problems = list(Problem.objects.select_related("subtopic__topic").prefetch_related("test_cases"))
    if not problems:
        raise ValueError("There are no problems yet. Run `python manage.py seed_problems` first.")

    rng = random.Random(seed)
    now = now or timezone.now()
    created = []

    for number in range(1, students + 1):
        student = User.objects.create_user(
            email=f"demo-student-{number:03d}@{DEMO_DOMAIN}",
            name=f"DEMO Student {number:03d} (fake)",
            password=None,  # no password: nobody can log in as a demo student
        )
        skill = rng.gauss(0, 1)  # the hidden ability of this fake student
        moment = now - timedelta(days=rng.randint(10, 50))
        tries = {}  # problem id -> how many attempts so far
        correct_in_topic = {}  # topic id -> correct attempts so far (a fake "learning effect")
        topic_pool = sorted({p.subtopic.topic_id for p in problems})
        topic_id = rng.choice(topic_pool)

        for _ in range(attempts_per_student):
            if rng.random() < 0.25:  # sometimes move to another topic
                topic_id = rng.choice(topic_pool)
            in_topic = [p for p in problems if p.subtopic.topic_id == topic_id]
            problem = rng.choice(in_topic)
            experience = 0.12 * correct_in_topic.get(topic_id, 0)
            logit = 1.3 * skill + 0.9 + experience - 1.2 * _DIFFICULTY_PENALTY[problem.difficulty]
            correct = rng.random() < 1 / (1 + math.exp(-logit))
            correct_in_topic[topic_id] = correct_in_topic.get(topic_id, 0) + int(correct)

            total = len(problem.test_cases.all())
            tries[problem.pk] = tries.get(problem.pk, 0) + 1
            speed = math.exp(-0.25 * skill + rng.gauss(0, 0.35))
            seconds = int(_BASE_TIME_SEC[problem.difficulty] * speed * (1.0 if correct else 1.3))
            moment += timedelta(minutes=rng.randint(10, 240))
            created.append(Attempt(
                student=student, problem=problem, source_code=DEMO_SOURCE_CODE,
                difficulty=problem.difficulty, is_correct=correct,
                tests_passed=total if correct else rng.randint(0, max(total - 1, 0)), tests_total=total,
                attempt_no=tries[problem.pk], time_taken_sec=max(seconds, 5),
                exec_time_ms=rng.randint(10, 300), submitted_at=min(moment, now),
            ))

    Attempt.objects.bulk_create(created, batch_size=500)
    analyzer = PerformanceAnalyzer()
    for student in demo_students():
        analyzer.sync_student(student)  # fake attempts were inserted in bulk: store their topic rows too
    return students, len(created)
