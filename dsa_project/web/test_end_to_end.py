"""End-to-end test (Step 12): the whole journey of two students through the real pages.

Code is really run (CodeEvaluator starts a Python process for every test case), so this test
takes a few seconds. Everything goes through the Django test client, like a browser.
"""

from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from analytics.models import TopicPerformance
from attempts.models import Attempt, TestCaseResult
from problems.models import Problem
from recommendations.models import Recommendation
from users.models import User

PASSWORD = "Strong#Pass123"
RIGHT = "n = int(input())\nprint(sum(map(int, input().split())))"  # solves "Sum of Array"
WRONG = "print(-99999)"  # runs, but is wrong on every test case


class EndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_problems", stdout=StringIO())

    def register_and_login(self, client, email, name):
        response = client.post(reverse("register"), {"name": name, "email": email, "password1": PASSWORD, "password2": PASSWORD})
        self.assertRedirects(response, reverse("login"))
        response = client.post(reverse("login"), {"username": email, "password": PASSWORD})
        self.assertRedirects(response, reverse("dashboard"))

    def submit(self, client, problem, code):
        client.get(reverse("problem_detail", args=[problem.pk]))  # opening the page starts the timer
        response = client.post(reverse("problem_detail", args=[problem.pk]), {"source_code": code})
        self.assertEqual(response.status_code, 302)
        return client.get(response["Location"])

    def test_full_journey_of_two_students(self):
        sum_problem = Problem.objects.get(title="Sum of Array")
        sam, mia = Client(), Client()

        # 1. Register and log in. A brand new student sees the empty states.
        self.register_and_login(sam, "sam@example.com", "Sam")
        dashboard = sam.get(reverse("dashboard"))
        self.assertContains(dashboard, "Let's solve your first problem")
        self.assertContains(sam.get(reverse("analytics")), "No charts yet")
        for name in ("api_trend", "api_topics"):
            self.assertEqual(sam.get(reverse(name)).json(), [])

        # 2. Open a problem: only sample test cases are shown.
        page = sam.get(reverse("problem_detail", args=[sum_problem.pk]))
        self.assertContains(page, sum_problem.title)
        hidden = sum_problem.test_cases.filter(is_sample=False).first()
        self.assertNotContains(page, hidden.expected_output + "</")

        # 3. A wrong solution, then correct ones. The result page shows every test case.
        result = self.submit(sam, sum_problem, WRONG)
        self.assertContains(result, "Recommended next")
        self.submit(sam, sum_problem, RIGHT)
        self.submit(sam, sum_problem, RIGHT)
        attempts = list(Attempt.objects.filter(student__email="sam@example.com").order_by("attempt_no"))
        self.assertEqual([a.is_correct for a in attempts], [False, True, True])
        self.assertEqual([a.attempt_no for a in attempts], [1, 2, 3])
        self.assertEqual(attempts[0].tests_passed, 0)
        self.assertEqual(attempts[1].tests_passed, attempts[1].tests_total)
        self.assertEqual(TestCaseResult.objects.filter(attempt=attempts[1]).count(), attempts[1].tests_total)

        # 4. TopicPerformance was updated for exactly this topic, and a recommendation was stored.
        topic = sum_problem.subtopic.topic
        row = TopicPerformance.objects.get(student__email="sam@example.com", topic=topic)
        self.assertEqual((row.total_attempts, round(row.accuracy, 2)), (3, 0.67))
        self.assertEqual(TopicPerformance.objects.count(), 1)
        self.assertIsNotNone(row.mastery_score)
        recommendation = Recommendation.objects.filter(student__email="sam@example.com").first()
        self.assertEqual(Recommendation.objects.filter(student__email="sam@example.com").count(), 3)
        self.assertTrue(recommendation.reason)
        self.assertNotEqual(recommendation.problem, sum_problem)  # a solved problem is not suggested again

        # 5. Dashboard and chart endpoints show Sam's data.
        dashboard = sam.get(reverse("dashboard"))
        self.assertContains(dashboard, "Overall skill")
        self.assertContains(dashboard, "Recommended next")
        self.assertContains(dashboard, "Sum of Array")
        topics = sam.get(reverse("api_topics")).json()
        self.assertEqual([t["topic"] for t in topics], [topic.name])
        self.assertEqual(topics[0]["attempts"], 3)
        self.assertEqual(sum(p["attempts"] for p in sam.get(reverse("api_trend")).json()), 3)
        difficulty = {d["difficulty"]: d for d in sam.get(reverse("api_difficulty")).json()}
        self.assertEqual(difficulty["Easy"]["attempts"], 3)
        self.assertContains(sam.get(reverse("analytics")), 'id="trend-chart"')
        self.assertContains(sam.get(reverse("roadmap")), topic.name)

        # 6. A second student sees none of Sam's data.
        self.register_and_login(mia, "mia@example.com", "Mia")
        self.assertContains(mia.get(reverse("dashboard")), "Let's solve your first problem")
        for name in ("api_trend", "api_topics"):
            self.assertEqual(mia.get(reverse(name)).json(), [])
        self.assertEqual(sum(d["attempts"] for d in mia.get(reverse("api_difficulty")).json()), 0)
        history = mia.get(reverse("attempt_history", args=[sum_problem.pk]))
        self.assertNotContains(history, "print(-99999)")
        self.assertNotContains(history, "sum(map(int")
        # Mia cannot open Sam's attempt through the result link either.
        sam_attempt = attempts[1]
        stolen = mia.get(f"{reverse('problem_detail', args=[sum_problem.pk])}?attempt={sam_attempt.pk}")
        self.assertNotContains(stolen, "sum(map(int")
        self.assertEqual(Recommendation.objects.filter(student__email="mia@example.com").count(), 0)

        # 7. Mia solves one problem: her numbers are separate from Sam's.
        self.submit(mia, sum_problem, RIGHT)
        self.assertEqual(sum(p["attempts"] for p in mia.get(reverse("api_trend")).json()), 1)
        self.assertEqual(sum(p["attempts"] for p in sam.get(reverse("api_trend")).json()), 3)
        self.assertEqual(TopicPerformance.objects.count(), 2)

    def test_forgot_password_journey(self):
        User.objects.create_user(email="sam@example.com", name="Sam", password=PASSWORD)
        client = Client()
        self.assertContains(client.get(reverse("login")), "Forgot your password?")
        response = client.post(reverse("password_reset"), {"email": "sam@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        link = [w for w in mail.outbox[0].body.split() if "/password-reset/" in w][0]
        path = "/" + link.split("/", 3)[3]
        response = client.get(path, follow=True)
        new_password = "Another#Pass456"
        response = client.post(response.request["PATH_INFO"], {"new_password1": new_password, "new_password2": new_password})
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertTrue(client.login(username="sam@example.com", password=new_password))

    def test_a_crashing_and_an_endless_solution_do_not_stop_the_app(self):
        problem = Problem.objects.get(title="Sum of Array")
        client = Client()
        self.register_and_login(client, "sam@example.com", "Sam")
        with self.settings(CODE_TIME_LIMIT_SEC=1):
            self.submit(client, problem, "raise ValueError('boom')")
            self.submit(client, problem, "while True:\n    pass")
        statuses = set(TestCaseResult.objects.values_list("status", flat=True))
        self.assertTrue({"ERROR", "TLE"} <= statuses)
        self.assertEqual(client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(Attempt.objects.count(), 2)
