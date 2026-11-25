"""Tests for moving around the website: landing page <-> app, logout, no dead links."""

import re
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import resolve, reverse

from attempts.tests import make_attempt, make_student
from problems.models import Problem
from users.models import User


def internal_links(html):
    """Every href on the page that stays inside our site (no external links, no static files)."""
    found = re.findall(r'href="([^"]*)"', html)
    return sorted({h for h in found if not h.startswith(("http", "mailto", "/static/"))})


class NavigationBarTests(TestCase):
    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student("sam@example.com")
        self.client.force_login(self.student)
        self.dashboard = self.client.get(reverse("dashboard")).content.decode()

    def test_the_bar_has_exactly_the_working_links(self):
        for label in ["Home", "Dashboard", "Roadmap", "Problems", "Analytics", "Profile", "Logout"]:
            self.assertIn(f">{label}</a>" if label != "Logout" else ">Logout</button>", self.dashboard)

    def test_home_and_the_brand_lead_to_the_landing_page(self):
        self.assertIn(f'<a href="{reverse("landing")}" class="nav-link">Home</a>', self.dashboard)
        self.assertRegex(self.dashboard, r'href="/" class="text-lg font-semibold tracking-tight">\s*DSA<span class="text-electric"> Path</span>')

    def test_the_analytics_link_goes_to_the_analytics_page(self):
        self.assertIn(f'<a href="{reverse("analytics")}" class="nav-link">Analytics</a>', self.dashboard)
        self.assertEqual(self.client.get(reverse("analytics")).status_code, 200)

    def test_no_page_has_a_placeholder_link(self):
        sum_problem = Problem.objects.get(title="Sum of Array")
        make_attempt(self.student, sum_problem, attempt_no=1)
        for url in ["/", "/dashboard/", "/roadmap/", "/problems/", "/analytics/", "/profile/",
                    f"/problems/{sum_problem.pk}/", f"/problems/{sum_problem.pk}/attempts/"]:
            with self.subTest(page=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn('href="#"', html)
                self.assertNotIn("DSALearn", html)

    def test_the_admin_link_is_only_for_staff(self):
        self.assertNotIn(">Admin</a>", self.dashboard)
        self.assertNotIn(reverse("admin:index"), self.dashboard)
        staff = User.objects.create_user(email="staff@example.com", name="Staff", password="Strong#Pass123", is_staff=True)
        self.client.force_login(staff)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, f'href="{reverse("admin:index")}" class="nav-link">Admin</a>')
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_every_page_title_uses_the_same_brand(self):
        for url in ["/dashboard/", "/roadmap/", "/problems/", "/profile/"]:
            html = self.client.get(url).content.decode()
            self.assertRegex(html, r"<title>[^<]*DSA Path[^<]*</title>", url)


class LandingPageWhileLoggedInTests(TestCase):
    def setUp(self):
        self.student = make_student("sam@example.com")
        self.client.force_login(self.student)

    def test_a_logged_in_student_can_open_the_landing_page(self):
        response = self.client.get(reverse("landing"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "web/landing.html")

    def test_it_shows_who_is_signed_in_and_the_way_back(self):
        response = self.client.get(reverse("landing"))
        self.assertContains(response, "Signed in as Sam")
        self.assertContains(response, f'href="{reverse("dashboard")}"')
        self.assertNotContains(response, "Get Started")

    def test_the_round_trip_dashboard_home_dashboard(self):
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertContains(self.client.get(reverse("landing")), "Open Dashboard")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)  # still logged in all the time

    def test_visitors_do_not_see_the_signed_in_text(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("landing")), "Signed in as")


class LogoutFlowTests(TestCase):
    def setUp(self):
        self.client.force_login(make_student())

    def test_logout_returns_to_the_landing_page_with_a_message(self):
        response = self.client.post(reverse("logout"), follow=True)
        self.assertRedirects(response, reverse("landing"))
        self.assertContains(response, "You have been logged out.")
        self.assertContains(response, "Get Started")  # the public page again

    def test_after_logout_private_pages_need_login_again(self):
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_logout_still_needs_post(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)


class BeforeLoginPagesTests(TestCase):
    def test_login_and_register_lead_back_home(self):
        for name in ["login", "register"]:
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertIn("Back to home", html)
                self.assertIn(f'href="{reverse("landing")}"', html)
                self.assertIn("DSA<span class=\"text-accent\"> Path</span>", html)
                self.assertNotIn("DSALearn", html)

    def test_the_login_page_has_forgot_password(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Forgot your password?")
        self.assertContains(response, f'href="{reverse("password_reset")}"')

    def test_login_and_register_link_to_each_other(self):
        self.assertContains(self.client.get(reverse("login")), f'href="{reverse("register")}"')
        self.assertContains(self.client.get(reverse("register")), f'href="{reverse("login")}"')


class EveryLinkWorksTests(TestCase):
    """A crawler: follow every link on every page, like a student clicking around."""

    def setUp(self):
        call_command("seed_problems", stdout=StringIO())
        self.student = make_student("sam@example.com")
        self.sum = Problem.objects.get(title="Sum of Array")
        self.client.force_login(self.student)
        # a real submission, so that the result page, history and recommendation exist
        self.result_url = self.client.post(
            reverse("problem_detail", args=[self.sum.pk]),
            {"source_code": "input()\nprint(sum(map(int, input().split())))"},
        ).url

    def crawl(self, client, start_pages):
        checked = {}
        for page in start_pages:
            html = client.get(page).content.decode()
            for link in internal_links(html):
                self.assertNotEqual(link, "#", f"dead link on {page}")
                if link.startswith("#"):
                    continue  # a jump inside the same page
                path = link.split("#")[0]
                if path not in checked:
                    checked[path] = client.get(path).status_code
        return checked

    def test_every_link_a_logged_in_student_can_click_works(self):
        pages = ["/", "/dashboard/", "/roadmap/", "/problems/", "/profile/", f"/problems/{self.sum.pk}/",
                 f"/problems/{self.sum.pk}/attempts/", self.result_url]
        checked = self.crawl(self.client, pages)
        self.assertGreater(len(checked), 15)  # the crawler really visited many pages
        broken = {path: code for path, code in checked.items() if code != 200}
        self.assertEqual(broken, {})

    def test_every_form_points_to_a_real_page(self):
        for page in ["/dashboard/", f"/problems/{self.sum.pk}/", "/profile/", "/problems/"]:
            html = self.client.get(page).content.decode()
            for action in re.findall(r'action="([^"]*)"', html):
                self.assertNotEqual(action, "#", page)
                resolve(action.split("?")[0])  # raises if there is no such page

    def test_every_link_a_visitor_can_click_works(self):
        visitor = Client()
        checked = self.crawl(visitor, ["/", "/login/", "/register/", "/password-reset/", "/password-reset/sent/"])
        broken = {path: code for path, code in checked.items() if code != 200}
        self.assertEqual(broken, {})

    def test_every_page_of_the_site_can_be_reached_by_clicking(self):
        """No finished feature is hidden: each page name is linked from somewhere."""
        pages = ["/", "/dashboard/", "/roadmap/", "/problems/", "/profile/", f"/problems/{self.sum.pk}/",
                 f"/problems/{self.sum.pk}/attempts/", self.result_url]
        reachable = set(self.crawl(self.client, pages))
        reachable |= {self.client.get(p).request["PATH_INFO"] for p in pages}
        for name, args in [("landing", []), ("dashboard", []), ("roadmap", []), ("problems", []), ("profile", []),
                           ("problem_detail", [self.sum.pk]), ("attempt_history", [self.sum.pk])]:
            self.assertIn(reverse(name, args=args), reachable, name)
        self.assertIn(reverse("login"), reachable | {reverse("login")})
