"""Loads a small sample set of problems so we can develop and test.

    python manage.py seed_problems

Safe to run again: a problem that already exists (same title in the same
subtopic) is skipped, so nothing the administrator edited is overwritten.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from problems.models import Problem, Subtopic, TestCase, Topic
from problems.seed_data import SEED_TOPICS


class Command(BaseCommand):
    help = "Load sample topics, subtopics, problems and test cases (safe to run twice)."

    @transaction.atomic  # all or nothing: no half-loaded data if something fails
    def handle(self, *args, **options):
        made = {"topics": 0, "subtopics": 0, "problems": 0, "test cases": 0}
        skipped = 0

        for topic_data in SEED_TOPICS:
            topic, created = Topic.objects.get_or_create(
                name=topic_data["name"], defaults={"order": topic_data["order"]}
            )
            made["topics"] += created

            for sub_data in topic_data["subtopics"]:
                subtopic, created = Subtopic.objects.get_or_create(
                    topic=topic, name=sub_data["name"], defaults={"order": sub_data["order"]}
                )
                made["subtopics"] += created

                for prob_data in sub_data["problems"]:
                    if Problem.objects.filter(subtopic=subtopic, title=prob_data["title"]).exists():
                        skipped += 1
                        continue
                    problem = Problem.objects.create(
                        subtopic=subtopic,
                        title=prob_data["title"],
                        statement=prob_data["statement"],
                        difficulty=prob_data["difficulty"],
                    )
                    made["problems"] += 1
                    for input_data, expected_output, is_sample in prob_data["tests"]:
                        TestCase.objects.create(
                            problem=problem,
                            input_data=input_data,
                            expected_output=expected_output,
                            is_sample=is_sample,
                        )
                        made["test cases"] += 1

        summary = ", ".join(f"{count} {name}" for name, count in made.items())
        self.stdout.write(self.style.SUCCESS(f"Created: {summary}."))
        if skipped:
            self.stdout.write(f"Skipped {skipped} problem(s) that already exist.")
