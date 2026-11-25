"""Tests for "Forgot your password?" (e-mail is only printed by default, never really sent)."""

import re

from django.contrib.auth.hashers import check_password
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import User

OLD = "Strong#Pass123"
NEW = "Brand#New-Pass-789"


def make_user(email="sam@example.com", **extra):
    return User.objects.create_user(email=email, name="Sam", password=OLD, **extra)


def reset_link(message):
    """The reset link inside an e-mail (as a path)."""
    return re.search(r"https?://[^/\s]+(/password-reset/\S+/)", message.body).group(1)


class ResetRequestTests(TestCase):
    url = "/password-reset/"

    def post(self, email="sam@example.com"):
        return self.client.post(self.url, {"email": email})

    def test_pages_open_without_login(self):
        for name in ["password_reset", "password_reset_done", "password_reset_complete"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_the_page_explains_what_to_do_and_leads_back(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Forgot your password?")
        self.assertContains(response, "Send reset link")
        self.assertContains(response, f'href="{reverse("login")}"')
        self.assertContains(response, f'href="{reverse("landing")}"')

    def test_a_registered_email_gets_one_email_with_a_link(self):
        make_user()
        response = self.post()
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["sam@example.com"])
        self.assertEqual(message.subject, "Reset your DSA Path password")
        self.assertIn("Hello Sam", message.body)
        self.assertRegex(message.body, r"/password-reset/[0-9A-Za-z_\-]+/[0-9A-Za-z\-]+/")
        self.assertIn("1 hour", message.body)
        self.assertNotIn("{{", message.body)

    def test_the_email_does_not_contain_the_password_or_its_hash(self):
        user = make_user()
        self.post()
        body = mail.outbox[0].body
        self.assertNotIn(OLD, body)
        self.assertNotIn(user.password, body)

    def test_the_email_address_is_not_case_sensitive(self):
        make_user()
        self.post("SAM@Example.COM")
        self.assertEqual(len(mail.outbox), 1)

    def test_an_unknown_email_looks_exactly_the_same_and_sends_nothing(self):
        make_user()
        known = self.post("sam@example.com")
        unknown = self.post("nobody@example.com")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)  # nobody can find out who is registered
        self.assertEqual(len(mail.outbox), 1)  # only the real one was sent

    def test_the_done_page_never_says_whether_the_address_exists(self):
        page = self.client.get(self.url_done())
        self.assertContains(page, "If an account exists")

    def url_done(self):
        return reverse("password_reset_done")

    def test_inactive_accounts_get_no_email(self):
        make_user(is_active=False)
        self.post()
        self.assertEqual(len(mail.outbox), 0)

    def test_accounts_without_a_password_get_no_email(self):
        User.objects.create_user(email="demo@demo.invalid", name="DEMO (fake)", password=None)
        self.post("demo@demo.invalid")
        self.assertEqual(len(mail.outbox), 0)

    def test_empty_and_wrong_emails_are_rejected_with_a_message(self):
        response = self.post("")
        self.assertContains(response, "This field is required.")
        response = self.post("not-an-email")
        self.assertContains(response, "Enter a valid e-mail address.")
        self.assertEqual(len(mail.outbox), 0)

    def test_the_form_needs_the_csrf_token(self):
        make_user()
        strict = Client(enforce_csrf_checks=True)
        self.assertEqual(strict.post(self.url, {"email": "sam@example.com"}).status_code, 403)
        self.assertEqual(len(mail.outbox), 0)

    def test_the_link_works_for_one_hour(self):
        from django.conf import settings

        self.assertEqual(settings.PASSWORD_RESET_TIMEOUT, 3600)

    def test_a_logged_in_student_can_also_use_it(self):
        user = make_user()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)


class ConsoleEmailNoticeTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_the_page_tells_where_to_find_the_link_when_email_is_only_printed(self):
        page = self.client.get(reverse("password_reset_done"))
        self.assertContains(page, "printed in the terminal window")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_the_note_is_not_shown_when_real_email_is_used(self):
        page = self.client.get(reverse("password_reset_done"))
        self.assertNotContains(page, "printed in the terminal")

    def test_the_default_setting_prints_the_email_and_sends_nothing_real(self):
        from pathlib import Path

        from django.conf import settings

        source = (Path(settings.BASE_DIR) / "dsa_learning" / "settings.py").read_text()
        self.assertRegex(source, r'os\.getenv\("EMAIL_BACKEND", "users\.email_backend\.ReadableConsoleEmailBackend"\)')

    @override_settings(EMAIL_BACKEND="users.email_backend.ReadableConsoleEmailBackend")
    def test_the_page_note_is_also_shown_for_the_readable_console_backend(self):
        self.assertContains(self.client.get(reverse("password_reset_done")), "printed in the terminal window")


class ReadableConsoleEmailTests(TestCase):
    """The printed e-mail must be easy to copy: the reset link stays on ONE line."""

    def print_email(self, body="x", **kwargs):
        from io import StringIO

        from django.core.mail import EmailMessage

        from users.email_backend import ReadableConsoleEmailBackend

        stream = StringIO()
        message = EmailMessage("Reset your password", body, "from@example.com", ["sam@example.com"])
        sent = ReadableConsoleEmailBackend(stream=stream).send_messages([message])
        return sent, stream.getvalue()

    def test_it_says_clearly_that_nothing_was_really_sent(self):
        sent, text = self.print_email()
        self.assertEqual(sent, 1)
        self.assertIn("NOT really sent", text)
        self.assertIn("To: sam@example.com", text)
        self.assertIn("Subject: Reset your password", text)

    def test_a_long_link_is_printed_in_one_piece_without_encoding(self):
        link = "http://127.0.0.1:8000/password-reset/MjQz/dgugjn-76b0c3245d5fe560ed91e5ba7cea18e9/"
        _, text = self.print_email(f"Open this link:\n\n{link}\n\nThanks")
        self.assertIn(f"\n{link}\n", text)  # the whole link on a line of its own
        self.assertEqual(cut_lines(text), [])  # no line cut with "=" (quoted-printable soft break)
        self.assertNotIn("=3D", text)

    def test_the_default_console_backend_would_have_cut_the_link(self):
        """Why this backend exists: Django's own console backend breaks long lines."""
        from io import StringIO

        from django.core.mail import EmailMessage
        from django.core.mail.backends.console import EmailBackend

        link = "http://127.0.0.1:8000/password-reset/MjQz/dgugjn-76b0c3245d5fe560ed91e5ba7cea18e9/"
        stream = StringIO()
        EmailBackend(stream=stream).send_messages([EmailMessage("S", f"Open:\n\n{link}\n", "a@b.c", ["x@y.z"])])
        self.assertIn("=\n", stream.getvalue())

    def test_the_real_reset_email_prints_a_copyable_link_that_works(self):
        import re
        import sys
        from io import StringIO
        from unittest import mock
        from urllib.parse import urlsplit

        make_user()
        printed = StringIO()
        with override_settings(EMAIL_BACKEND="users.email_backend.ReadableConsoleEmailBackend"):
            with mock.patch.object(sys, "stdout", printed):  # what the server terminal would show
                self.client.post("/password-reset/", {"email": "sam@example.com"})
        text = printed.getvalue()
        self.assertEqual(cut_lines(text), [])
        link = re.search(r"^(http\S+/password-reset/\S+/)$", text, re.M)
        self.assertIsNotNone(link, text)
        self.assertEqual(Client().get(urlsplit(link.group(1)).path).status_code, 302)  # the printed link really works


def cut_lines(text):
    """Lines that end with "=" and are not just a banner of = signs: the mark of a cut line."""
    return [line for line in text.splitlines() if line.endswith("=") and set(line) != {"="}]


class ChooseNewPasswordTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.post("/password-reset/", {"email": "sam@example.com"})
        self.link = reset_link(mail.outbox[0])

    def start(self, client=None):
        """Open the link: Django moves the token into the session and redirects to a clean address."""
        client = client or self.client
        response = client.get(self.link)
        self.assertEqual(response.status_code, 302)
        return response.url

    def test_the_whole_flow_from_the_email_to_logging_in(self):
        form_url = self.start()
        page = self.client.get(form_url)
        self.assertContains(page, "Choose a new password")
        self.assertContains(page, "Change password")

        response = self.client.post(form_url, {"new_password1": NEW, "new_password2": NEW})
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertContains(self.client.get(reverse("password_reset_complete")), "Your password is changed")

        self.user.refresh_from_db()
        self.assertTrue(check_password(NEW, self.user.password))
        fresh = Client()
        self.assertTrue(fresh.login(username="sam@example.com", password=NEW))  # the new password works
        self.assertFalse(Client().login(username="sam@example.com", password=OLD))  # the old one does not

    def test_the_link_works_only_once(self):
        form_url = self.start()
        self.client.post(form_url, {"new_password1": NEW, "new_password2": NEW})
        again = Client().get(self.link)
        self.assertContains(again, "This link does not work")
        self.assertContains(again, "Get a new link")

    def test_weak_passwords_are_rejected_and_nothing_changes(self):
        form_url = self.start()
        for password in ["Ab1#", "password123", "83749261508", "sam@example.com"]:
            with self.subTest(password=password):
                response = self.client.post(form_url, {"new_password1": password, "new_password2": password})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "border-red-300")  # the same red error box as everywhere
        self.user.refresh_from_db()
        self.assertTrue(check_password(OLD, self.user.password))

    def test_passwords_that_do_not_match_are_rejected(self):
        form_url = self.start()
        response = self.client.post(form_url, {"new_password1": NEW, "new_password2": NEW + "x"})
        self.assertContains(response, "The two password fields")
        self.user.refresh_from_db()
        self.assertTrue(check_password(OLD, self.user.password))

    def test_the_form_shows_the_password_rules(self):
        self.assertContains(self.client.get(self.start()), "at least 8 characters")

    def test_an_expired_link_does_not_work(self):
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            page = Client().get(self.link)
        self.assertContains(page, "This link does not work")

    def test_a_damaged_link_does_not_work_and_does_not_crash(self):
        uid, token = self.link.strip("/").split("/")[1:3]
        for path in [f"/password-reset/{uid}/wrong-token/", f"/password-reset/AAAA/{token}/",
                     "/password-reset/!!!/%3F%3F%3F/", f"/password-reset/{uid}/{token[:-3]}xyz/"]:
            with self.subTest(path=path):
                response = Client().get(path, follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "This link does not work")

    def test_a_link_cannot_be_used_for_another_account(self):
        other = make_user("other@example.com")
        uid, token = self.link.strip("/").split("/")[1:3]
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes

        other_uid = urlsafe_base64_encode(force_bytes(other.pk))
        response = Client().get(f"/password-reset/{other_uid}/{token}/", follow=True)
        self.assertContains(response, "This link does not work")

    def test_changing_the_password_logs_out_other_sessions(self):
        logged_in = Client()
        self.assertTrue(logged_in.login(username="sam@example.com", password=OLD))
        self.assertEqual(logged_in.get(reverse("dashboard")).status_code, 200)

        resetter = Client()  # another browser asks for a reset (after the login above)
        resetter.post("/password-reset/", {"email": "sam@example.com"})
        link = reset_link(mail.outbox[-1])
        form_url = resetter.get(link).url
        resetter.post(form_url, {"new_password1": NEW, "new_password2": NEW})

        self.assertEqual(logged_in.get(reverse("dashboard")).status_code, 302)  # sent to the login page

    def test_logging_in_after_asking_for_the_email_cancels_the_link(self):
        """Django ties the link to the last login: whoever remembers the password and logs in, kills the link."""
        self.assertTrue(Client().login(username="sam@example.com", password=OLD))
        self.assertContains(Client().get(self.link), "This link does not work")

    def test_the_form_needs_the_csrf_token(self):
        form_url = self.start()
        strict = Client(enforce_csrf_checks=True)
        strict.cookies = self.client.cookies
        self.assertEqual(strict.post(form_url, {"new_password1": NEW, "new_password2": NEW}).status_code, 403)

    def test_the_pages_have_no_navigation_bar_and_the_brand(self):
        page = self.client.get(self.start())
        self.assertNotContains(page, "Roadmap")
        self.assertContains(page, "Back to home")
        self.assertNotContains(page, "DSALearn")
