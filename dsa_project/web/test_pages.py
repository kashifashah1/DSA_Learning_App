"""Tests for the Problem list page and the Roadmap page."""

from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from attempts.tests import make_attempt, make_student
from problems.models import Problem, Subtopic, Topic


class ProblemListPageTests(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student()
        self.client.force_login(self.student)
        self.url = reverse("problems")

    def rows(self, **params):
        return self.client.get(self.url, params).context["rows"]

    def test_page_needs_login(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_shows_all_problems_and_navigation_bar(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rows"]), 12)
        self.assertContains(response, "Sum of Array")
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Profile", "Logout"]:
            self.assertContains(response, label)

    def test_filter_by_topic_in_the_url(self):
        arrays = Topic.objects.get(name="Arrays")
        rows = self.rows(topic=arrays.pk)
        self.assertEqual(len(rows), 4)

    def test_filter_by_subtopic_in_the_url(self):
        sub = Subtopic.objects.get(name="Sorting")
        self.assertEqual(len(self.rows(subtopic=sub.pk)), 2)

    def test_filter_by_difficulty_in_the_url(self):
        self.assertEqual(len(self.rows(difficulty="Hard")), 3)

    def test_all_three_filters_together(self):
        strings = Topic.objects.get(name="Strings")
        sub = Subtopic.objects.get(topic=strings, name="Frequency and Counting")
        rows = self.rows(topic=strings.pk, subtopic=sub.pk, difficulty="Hard")
        self.assertEqual([r.problem.title for r in rows], ["Longest Substring Without Repeating Characters"])

    def test_chosen_filters_stay_selected_in_the_form(self):
        arrays = Topic.objects.get(name="Arrays")
        response = self.client.get(self.url, {"topic": arrays.pk, "difficulty": "Easy"})
        self.assertContains(response, f'<option value="{arrays.pk}" selected>')
        self.assertContains(response, '<option value="Easy" selected>')

    def test_message_when_no_problem_matches(self):
        arrays = Topic.objects.get(name="Arrays")
        response = self.client.get(self.url, {"topic": arrays.pk, "difficulty": "Hard"})
        self.assertContains(response, "No problems match these filters.")
        self.assertEqual(len(response.context["rows"]), 0)

    def test_message_when_there_are_no_problems_at_all(self):
        Problem.objects.all().delete()
        response = self.client.get(self.url)
        self.assertContains(response, "No problems have been added yet.")
        self.assertNotContains(response, "No problems match")

    def test_subtopic_from_another_topic_is_rejected(self):
        strings = Topic.objects.get(name="Strings")
        sorting = Subtopic.objects.get(name="Sorting")
        response = self.client.get(self.url, {"topic": strings.pk, "subtopic": sorting.pk})
        self.assertContains(response, "This subtopic does not belong to the selected topic.")

    def test_wrong_filter_values_show_an_error_and_do_not_crash(self):
        for params in [{"topic": "abc"}, {"topic": "99999"}, {"subtopic": "x"}, {"difficulty": "Impossible"}]:
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Select a valid choice.")
                self.assertEqual(len(response.context["rows"]), 12)  # no filter applied

    def test_status_marks_for_the_logged_in_student(self):
        solved = Problem.objects.get(title="Sum of Array")
        tried = Problem.objects.get(title="Palindrome Check")
        make_attempt(self.student, solved, is_correct=True)
        make_attempt(self.student, tried, is_correct=False)
        status = {row.problem.title: row.status for row in self.rows()}
        self.assertEqual(status["Sum of Array"], "solved")
        self.assertEqual(status["Palindrome Check"], "attempted")
        self.assertEqual(status["Count Vowels"], "not_attempted")

    def test_status_words_are_shown_on_the_page(self):
        make_attempt(self.student, Problem.objects.get(title="Sum of Array"), is_correct=True)
        response = self.client.get(self.url, {"difficulty": "Easy"})
        self.assertContains(response, "Solved")
        self.assertContains(response, "Not attempted")

    def test_another_students_attempts_are_not_shown(self):
        other = make_student("other@example.com")
        make_attempt(other, Problem.objects.get(title="Sum of Array"), is_correct=True)
        status = {row.problem.title: row.status for row in self.rows()}
        self.assertEqual(status["Sum of Array"], "not_attempted")

    def test_number_of_database_queries_does_not_grow_with_problems(self):
        make_attempt(self.student, Problem.objects.get(title="Sum of Array"), is_correct=True)
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url)

        subtopic = Subtopic.objects.first()
        for number in range(30):
            Problem.objects.create(title=f"Extra {number}", statement="S", difficulty="Easy", subtopic=subtopic)
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url)
        self.assertEqual(len(small), len(large))


class RoadmapPageTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.client.force_login(self.student)
        self.url = reverse("roadmap")

    def test_page_needs_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('login')}?next={self.url}")

    def test_lists_topics_and_subtopics_in_order(self):
        call_command("seed_problems", stdout=StringIO())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        positions = [text.index(name) for name in ["Arrays", "Strings", "Searching and Sorting"]]
        self.assertEqual(positions, sorted(positions))
        self.assertContains(response, "Traversal and Counting")
        self.assertContains(response, "Frequency and Counting")

    def test_every_topic_says_not_enough_data_for_a_new_student(self):
        call_command("seed_problems", stdout=StringIO())
        response = self.client.get(self.url)
        self.assertContains(response, "Not enough data yet", count=3)  # one per topic

    def test_shows_solved_count_and_link_to_filtered_list(self):
        call_command("seed_problems", stdout=StringIO())
        sub = Subtopic.objects.get(name="Binary Search")
        response = self.client.get(self.url)
        self.assertContains(response, "0 of 2 solved")
        self.assertContains(response, f"{reverse('problems')}?subtopic={sub.pk}")

    def test_message_when_there_are_no_topics(self):
        response = self.client.get(self.url)
        self.assertContains(response, "No topics have been added yet.")

    def test_navigation_bar_is_shown(self):
        response = self.client.get(self.url)
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Profile", "Logout"]:
            self.assertContains(response, label)
