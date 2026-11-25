"""Tests for Step 1: registration, login, logout, profile, login-required rule."""

from django.contrib.auth.hashers import check_password
from django.test import Client, TestCase
from django.urls import reverse

from .models import User

GOOD_PASSWORD = "Strong#Pass123"
LOGIN_ERROR = "The e-mail or password is incorrect."


def make_user(email="sam@example.com", name="Sam", password=GOOD_PASSWORD, **extra):
    return User.objects.create_user(email=email, name=name, password=password, **extra)


class UserModelTests(TestCase):
    def test_login_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_email_is_saved_in_lower_case(self):
        user = make_user(email="  Sam@Example.COM ")
        self.assertEqual(user.email, "sam@example.com")

    def test_password_is_hashed(self):
        user = make_user()
        self.assertNotEqual(user.password, GOOD_PASSWORD)
        self.assertTrue(check_password(GOOD_PASSWORD, user.password))

    def test_new_user_is_active_student_not_staff(self):
        user = make_user()
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertIsNotNone(user.date_joined)

    def test_email_and_name_are_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", name="Sam", password=GOOD_PASSWORD)
        with self.assertRaises(ValueError):
            User.objects.create_user(email="a@b.com", name="", password=GOOD_PASSWORD)

    def test_superuser_is_staff(self):
        admin = User.objects.create_superuser(email="a@b.com", name="Admin", password=GOOD_PASSWORD)
        self.assertTrue(admin.is_staff)


class RegistrationTests(TestCase):
    url = "/register/"

    def post(self, **overrides):
        data = {
            "name": "Sam",
            "email": "sam@example.com",
            "password1": GOOD_PASSWORD,
            "password2": GOOD_PASSWORD,
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_page_opens_without_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_successful_registration(self):
        response = self.post()
        self.assertRedirects(response, reverse("login"))
        user = User.objects.get(email="sam@example.com")
        self.assertEqual(user.name, "Sam")
        self.assertFalse(user.is_staff)
        self.assertTrue(check_password(GOOD_PASSWORD, user.password))  # stored hashed

    def test_success_message_is_shown_on_login_page(self):
        response = self.post(follow=False)
        response = self.client.get(response.url)
        self.assertContains(response, "Your account is created")

    def test_empty_fields_are_rejected_and_named(self):
        for field, label in [("name", "Name"), ("email", "E-mail"), ("password1", "Password")]:
            with self.subTest(field=field):
                response = self.post(**{field: ""})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"{label}: This field is required.")
                self.assertEqual(User.objects.count(), 0)

    def test_blank_spaces_only_name_is_rejected(self):
        response = self.post(name="   ")
        self.assertContains(response, "Name: This field is required.")
        self.assertEqual(User.objects.count(), 0)

    def test_wrong_email_format_is_rejected(self):
        for bad in ["samexample.com", "sam@", "sam@@example.com", "sam example@x.com"]:
            with self.subTest(email=bad):
                response = self.post(email=bad)
                self.assertContains(response, "Enter a valid e-mail address.")
                self.assertEqual(User.objects.count(), 0)

    def test_already_registered_email_is_rejected(self):
        make_user(email="sam@example.com")
        response = self.post(name="Other")
        self.assertContains(response, "This e-mail is already registered.")
        self.assertEqual(User.objects.count(), 1)

    def test_already_registered_email_ignores_upper_case(self):
        make_user(email="sam@example.com")
        response = self.post(email="SAM@Example.com")
        self.assertContains(response, "This e-mail is already registered.")
        self.assertEqual(User.objects.count(), 1)

    def test_weak_passwords_are_rejected(self):
        weak = {
            "short": "Ab1#",
            "common": "password123",
            "only digits": "83749261508",
            "like the e-mail": "sam@example.com",
        }
        for why, password in weak.items():
            with self.subTest(why=why):
                response = self.post(password1=password, password2=password)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Password:")
                self.assertEqual(User.objects.count(), 0)

    def test_password_mismatch_is_rejected(self):
        response = self.post(password2="Different#Pass456")
        self.assertContains(response, "The two passwords do not match.")
        self.assertEqual(User.objects.count(), 0)

    def test_several_problems_are_all_shown(self):
        response = self.post(name="", email="bad", password1="1", password2="1")
        self.assertContains(response, "Name: This field is required.")
        self.assertContains(response, "E-mail: Enter a valid e-mail address.")
        self.assertContains(response, "Password:")

    def test_no_navigation_bar_on_registration_page(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "Roadmap")

    def test_logged_in_user_is_sent_to_dashboard(self):
        self.client.force_login(make_user())
        self.assertRedirects(self.client.get(self.url), reverse("dashboard"))


class LoginTests(TestCase):
    url = "/login/"

    def setUp(self):
        self.user = make_user()

    def test_page_opens_without_login_and_has_no_navbar(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Roadmap")

    def test_login_with_email_and_password(self):
        response = self.client.post(self.url, {"username": "sam@example.com", "password": GOOD_PASSWORD})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_ignores_email_case(self):
        response = self.client.post(self.url, {"username": "SAM@Example.com", "password": GOOD_PASSWORD})
        self.assertRedirects(response, reverse("dashboard"))

    def test_wrong_password_gives_one_general_error(self):
        response = self.client.post(self.url, {"username": "sam@example.com", "password": "wrong"})
        self.assertContains(response, LOGIN_ERROR)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unknown_email_gives_the_same_error(self):
        wrong_password = self.client.post(self.url, {"username": "sam@example.com", "password": "wrong"})
        unknown_email = self.client.post(self.url, {"username": "nobody@example.com", "password": "wrong"})
        self.assertContains(unknown_email, LOGIN_ERROR)
        # The error text is identical, so nobody can find out which e-mails are registered.
        self.assertEqual(
            wrong_password.context["form"].non_field_errors(),
            unknown_email.context["form"].non_field_errors(),
        )

    def test_inactive_account_gives_the_same_general_error(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {"username": "sam@example.com", "password": GOOD_PASSWORD})
        self.assertContains(response, LOGIN_ERROR)

    def test_empty_login_is_rejected(self):
        response = self.client.post(self.url, {"username": "", "password": ""})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_goes_back_to_the_page_asked_for(self):
        response = self.client.post(
            self.url + "?next=/profile/", {"username": "sam@example.com", "password": GOOD_PASSWORD}
        )
        self.assertRedirects(response, "/profile/")

    def test_login_does_not_follow_a_link_to_another_site(self):
        response = self.client.post(
            self.url + "?next=https://evil.example.com/", {"username": "sam@example.com", "password": GOOD_PASSWORD}
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_login_form_needs_csrf_token(self):
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(self.url, {"username": "sam@example.com", "password": GOOD_PASSWORD})
        self.assertEqual(response.status_code, 403)


class LogoutTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user())

    def test_logout_with_post(self):
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("landing"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_by_link_is_not_allowed(self):
        response = self.client.get(reverse("logout"))
        self.assertEqual(response.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_navigation_bar_has_a_logout_form(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'action="/logout/"')


class LoginRequiredTests(TestCase):
    def test_pages_need_login(self):
        for name in ["dashboard", "profile"]:
            with self.subTest(page=name):
                url = reverse(name)
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_admin_needs_login(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)

    def test_normal_student_cannot_use_admin(self):
        self.client.force_login(make_user())
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)  # sent away to the admin login page
        self.assertIn("/admin/login/", response.url)

    def test_staff_can_open_admin(self):
        self.client.force_login(make_user(email="staff@example.com", is_staff=True))
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_navigation_bar_shows_on_logged_in_pages(self):
        self.client.force_login(make_user())
        response = self.client.get(reverse("profile"))
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Profile", "Logout"]:
            self.assertContains(response, label)


class ProfileTests(TestCase):
    url = "/profile/"

    def setUp(self):
        self.user = make_user()
        self.other = make_user(email="other@example.com", name="Other")
        self.client.force_login(self.user)

    def test_shows_own_details_only(self):
        response = self.client.get(self.url)
        self.assertContains(response, "sam@example.com")
        self.assertNotContains(response, "other@example.com")

    def test_edit_name_and_email(self):
        response = self.client.post(self.url, {"name": "Samira", "email": "New@Example.com"})
        self.assertRedirects(response, self.url)
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Samira")
        self.assertEqual(self.user.email, "new@example.com")
        # the password is untouched and the student stays logged in
        self.assertTrue(check_password(GOOD_PASSWORD, self.user.password))
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_success_message_after_saving(self):
        response = self.client.post(self.url, {"name": "Samira", "email": "sam@example.com"}, follow=True)
        self.assertContains(response, "Your profile is updated.")

    def test_keeping_own_email_is_allowed(self):
        response = self.client.post(self.url, {"name": "Samira", "email": "sam@example.com"})
        self.assertRedirects(response, self.url)

    def test_email_of_another_student_is_rejected(self):
        response = self.client.post(self.url, {"name": "Sam", "email": "OTHER@example.com"})
        self.assertContains(response, "This e-mail is already registered.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "sam@example.com")

    def test_wrong_email_format_is_rejected(self):
        response = self.client.post(self.url, {"name": "Sam", "email": "not-an-email"})
        self.assertContains(response, "Enter a valid e-mail address.")

    def test_empty_name_is_rejected(self):
        response = self.client.post(self.url, {"name": "  ", "email": "sam@example.com"})
        self.assertContains(response, "Name: This field is required.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Sam")

    def test_profile_form_needs_csrf_token(self):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(self.user)
        response = strict_client.post(self.url, {"name": "Hacked", "email": "sam@example.com"})
        self.assertEqual(response.status_code, 403)
