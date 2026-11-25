"""Step 4 tests: TestCaseResult, insert-only rule, student filter helper, read-only admin."""

from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from problems.models import TestCase as ProblemTestCase
from users.models import User

from .models import Attempt, InsertOnlyError, TestCaseResult
from .tests import make_attempt, make_problem, make_student


def make_result(attempt, test_case=None, status="PASSED", **extra):
    values = dict(attempt=attempt, test_case=test_case, status=status, exec_time_ms=12)
    values.update(extra)
    return TestCaseResult.objects.create(**values)


class AttemptTableRulesTests(TestCase):
    """Constraints and index from the master prompt."""

    def test_unique_constraint_and_index_exist(self):
        constraint_fields = [tuple(c.fields) for c in Attempt._meta.constraints]
        self.assertIn(("student", "problem", "attempt_no"), constraint_fields)
        index_fields = [tuple(i.fields) for i in Attempt._meta.indexes]
        self.assertIn(("student", "submitted_at"), index_fields)

    def test_display_helpers(self):
        student, problem = make_student(), make_problem()
        attempt = make_attempt(student, problem, time_taken_sec=45, exec_time_ms=None)
        self.assertEqual(attempt.time_taken_display, "45 s")
        self.assertEqual(attempt.exec_time_display, "Not available")
        slow = make_attempt(student, problem, attempt_no=2, time_taken_sec=200, exec_time_ms=130)
        self.assertEqual(slow.time_taken_display, "3 min 20 s")
        self.assertEqual(slow.exec_time_display, "130 ms")


class AttemptCannotBeChangedTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.problem = make_problem()
        self.attempt = make_attempt(self.student, self.problem, is_correct=False)

    def test_new_attempt_can_be_inserted(self):
        make_attempt(self.student, self.problem, attempt_no=2)
        self.assertEqual(Attempt.objects.count(), 2)

    def test_cannot_edit_an_attempt(self):
        self.attempt.is_correct = True
        with self.assertRaises(InsertOnlyError):
            self.attempt.save()
        self.assertFalse(Attempt.objects.get(pk=self.attempt.pk).is_correct)

    def test_cannot_save_an_attempt_again_even_without_changes(self):
        with self.assertRaises(InsertOnlyError):
            self.attempt.save()

    def test_cannot_edit_with_update_fields(self):
        self.attempt.tests_passed = 3
        with self.assertRaises(InsertOnlyError):
            self.attempt.save(update_fields=["tests_passed"])

    def test_cannot_overwrite_an_attempt_by_reusing_its_id(self):
        clone = Attempt(
            id=self.attempt.pk, student=self.student, problem=self.problem, source_code="cheat",
            difficulty="Easy", is_correct=True, tests_passed=3, tests_total=3, attempt_no=9, time_taken_sec=1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            clone.save()
        self.assertEqual(Attempt.objects.get(pk=self.attempt.pk).source_code, "print(1)")

    def test_cannot_delete_an_attempt(self):
        with self.assertRaises(InsertOnlyError):
            self.attempt.delete()
        self.assertEqual(Attempt.objects.count(), 1)

    def test_cannot_update_many_attempts_at_once(self):
        with self.assertRaises(InsertOnlyError):
            Attempt.objects.all().update(is_correct=True)
        with self.assertRaises(InsertOnlyError):
            Attempt.objects.update(is_correct=True)
        with self.assertRaises(InsertOnlyError):
            self.student.attempts.update(is_correct=True)  # through the student's related manager
        self.assertFalse(Attempt.objects.get(pk=self.attempt.pk).is_correct)

    def test_cannot_bulk_update_attempts(self):
        self.attempt.is_correct = True
        with self.assertRaises(InsertOnlyError):
            Attempt.objects.bulk_update([self.attempt], ["is_correct"])

    def test_cannot_delete_many_attempts_at_once(self):
        with self.assertRaises(InsertOnlyError):
            Attempt.objects.all().delete()
        with self.assertRaises(InsertOnlyError):
            Attempt.objects.filter(student=self.student).delete()
        self.assertEqual(Attempt.objects.count(), 1)

    def test_update_or_create_cannot_edit_an_existing_attempt(self):
        with self.assertRaises(InsertOnlyError):
            Attempt.objects.update_or_create(
                student=self.student, problem=self.problem, attempt_no=1, defaults={"is_correct": True}
            )
        self.assertFalse(Attempt.objects.get(pk=self.attempt.pk).is_correct)


class TestCaseResultTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.problem = make_problem()
        self.test_case = ProblemTestCase.objects.create(
            problem=self.problem, input_data="1", expected_output="1", is_sample=True
        )
        self.attempt = make_attempt(self.student, self.problem)

    def test_result_is_stored_for_an_attempt(self):
        result = make_result(self.attempt, self.test_case, status="FAILED", error_message="wrong answer")
        self.assertEqual(self.attempt.results.get(), result)
        self.assertEqual(result.error_message, "wrong answer")

    def test_status_choices(self):
        self.assertEqual(
            [value for value, _ in TestCaseResult.Status.choices], ["PASSED", "FAILED", "TLE", "ERROR"]
        )

    def test_error_message_is_empty_by_default(self):
        self.assertEqual(make_result(self.attempt, self.test_case).error_message, "")

    def test_results_come_back_in_the_order_they_were_stored(self):
        first = make_result(self.attempt, self.test_case, status="PASSED")
        second = make_result(self.attempt, None, status="TLE")
        self.assertEqual(list(self.attempt.results.all()), [first, second])

    def test_result_stays_when_the_test_case_is_deleted(self):
        result = make_result(self.attempt, self.test_case)
        self.test_case.delete()  # the administrator removes a test case
        result.refresh_from_db()
        self.assertIsNone(result.test_case)
        self.assertEqual(TestCaseResult.objects.count(), 1)

    def test_result_cannot_be_edited_or_deleted(self):
        result = make_result(self.attempt, self.test_case)
        result.status = "FAILED"
        with self.assertRaises(InsertOnlyError):
            result.save()
        with self.assertRaises(InsertOnlyError):
            result.delete()
        with self.assertRaises(InsertOnlyError):
            TestCaseResult.objects.all().update(status="FAILED")
        with self.assertRaises(InsertOnlyError):
            TestCaseResult.objects.all().delete()
        self.assertEqual(TestCaseResult.objects.get().status, "PASSED")


class ForStudentHelperTests(TestCase):
    def setUp(self):
        self.sam = make_student("sam@example.com")
        self.priya = make_student("priya@example.com")
        self.problem = make_problem()
        self.sam_attempt = make_attempt(self.sam, self.problem)
        self.priya_attempt = make_attempt(self.priya, self.problem)

    def test_returns_only_that_students_attempts(self):
        self.assertEqual(list(Attempt.objects.for_student(self.sam)), [self.sam_attempt])
        self.assertEqual(list(Attempt.objects.for_student(self.priya)), [self.priya_attempt])

    def test_anonymous_or_missing_user_gets_nothing(self):
        self.assertEqual(Attempt.objects.for_student(AnonymousUser()).count(), 0)
        self.assertEqual(Attempt.objects.for_student(None).count(), 0)

    def test_can_be_chained_with_other_filters(self):
        other_problem = make_problem("Other")
        make_attempt(self.sam, other_problem)
        mine = Attempt.objects.for_student(self.sam).filter(problem=self.problem)
        self.assertEqual(list(mine), [self.sam_attempt])


class AttemptAdminTests(TestCase):
    """Staff can look at attempts in the admin site, but not add, edit or delete them."""

    def setUp(self):
        self.staff = User.objects.create_user(
            email="admin@example.com", name="Admin", password="Strong#Pass123", is_staff=True
        )
        self.student = make_student()
        self.problem = make_problem()
        self.attempt = make_attempt(self.student, self.problem)
        make_result(self.attempt, None, status="FAILED")
        self.client.force_login(self.staff)
        self.change_url = reverse("admin:attempts_attempt_change", args=[self.attempt.pk])

    def test_staff_can_list_and_view_attempts(self):
        self.assertEqual(self.client.get(reverse("admin:attempts_attempt_changelist")).status_code, 200)
        response = self.client.get(self.change_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')  # no Save button: the page is read-only

    def test_test_case_results_are_shown_read_only_inside_the_attempt(self):
        response = self.client.get(self.change_url)
        self.assertContains(response, "FAILED")
        self.assertNotContains(response, "results-0-status")  # no input box for it

    def test_cannot_add_an_attempt(self):
        self.assertEqual(self.client.get(reverse("admin:attempts_attempt_add")).status_code, 403)

    def test_cannot_edit_an_attempt(self):
        response = self.client.post(self.change_url, {"tests_passed": 3, "is_correct": "on"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Attempt.objects.get(pk=self.attempt.pk).is_correct)

    def test_cannot_delete_an_attempt(self):
        url = reverse("admin:attempts_attempt_delete", args=[self.attempt.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_delete_selected_action_is_not_offered(self):
        response = self.client.get(reverse("admin:attempts_attempt_changelist"))
        self.assertNotContains(response, "delete_selected")

    def test_cannot_delete_a_student_who_has_attempts(self):
        url = reverse("admin:users_user_delete", args=[self.student.pk])
        self.client.post(url, {"post": "yes"})
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())
        self.assertEqual(Attempt.objects.count(), 1)

    def test_students_cannot_open_attempt_admin_pages(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("admin:attempts_attempt_changelist"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)
