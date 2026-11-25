"""Tests for the public landing page, the public layout and the shared design system."""

from django.test import TestCase
from django.urls import reverse

from users.models import User


class LandingPageTests(TestCase):
    def setUp(self):
        self.url = reverse("landing")
        self.response = self.client.get(self.url)

    # --- access ------------------------------------------------------------
    def test_landing_page_is_at_the_site_root(self):
        self.assertEqual(self.url, "/")

    def test_visitors_can_open_it_without_login(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertTemplateUsed(self.response, "web/landing.html")
        self.assertTemplateUsed(self.response, "public_base.html")

    def test_private_pages_still_need_login(self):
        for name in ["dashboard", "roadmap", "problems", "profile"]:
            with self.subTest(page=name):
                url = reverse(name)
                self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")

    def test_dashboard_placeholder_moved_to_its_own_url(self):
        self.assertEqual(reverse("dashboard"), "/dashboard/")

    # --- public navigation -------------------------------------------------
    def test_public_navigation_links(self):
        for label in ["Home", "Features", "How It Works", "About Project", "Login", "Get Started"]:
            self.assertContains(self.response, label)
        self.assertContains(self.response, "DSA<span")  # the text logo

    def test_in_page_links_point_at_real_sections(self):
        for anchor in ["features", "how-it-works", "about"]:
            with self.subTest(anchor=anchor):
                self.assertContains(self.response, f'id="{anchor}"')
                self.assertContains(self.response, f'href="/#{anchor}"')

    def test_login_and_get_started_use_the_right_urls(self):
        self.assertContains(self.response, f'href="{reverse("login")}"')
        self.assertContains(self.response, f'href="{reverse("register")}"')

    def test_start_learning_button_goes_to_registration(self):
        self.assertContains(self.response, f'href="{reverse("register")}" class="btn btn-primary">Start Learning')

    def test_explore_features_button_goes_to_features_section(self):
        self.assertContains(self.response, 'href="#features" class="btn btn-secondary">Explore Features')

    def test_private_navigation_is_not_mixed_in(self):
        for name in ["roadmap", "problems", "profile", "logout"]:
            with self.subTest(link=name):
                self.assertNotContains(self.response, f'href="{reverse(name)}"')
                self.assertNotContains(self.response, f'action="{reverse(name)}"')

    # --- content -----------------------------------------------------------
    def test_hero_headline_and_both_buttons(self):
        self.assertContains(self.response, "Learn DSA at Your Pace. Improve with Every Attempt.")
        self.assertContains(self.response, "Start Learning")
        self.assertContains(self.response, "Explore Features")

    def test_four_features_are_listed(self):
        for title in [
            "Structured DSA Roadmap",
            "Practice Problems",
            "Performance Analytics",
            "Adaptive Recommendations",
        ]:
            self.assertContains(self.response, title)

    def test_how_it_works_has_three_steps(self):
        for step in ["Solve a DSA problem", "Review your results", "Practise what is recommended"]:
            self.assertContains(self.response, step)

    def test_product_preview_is_labelled_as_illustrative(self):
        self.assertContains(self.response, "Illustrative sample")
        self.assertContains(self.response, "Sample data for illustration only")
        for part in ["Topic mastery", "Recent submissions", "Suggested next"]:
            self.assertContains(self.response, part)

    def test_about_section_is_honest_about_the_ml_model(self):
        self.assertContains(self.response, "student")
        self.assertContains(self.response, "When enough attempt data has been collected")
        text = self.response.content.decode().lower()
        for claim in ["already trained", "accuracy of", "testimonial", "lorem ipsum"]:
            self.assertNotIn(claim, text)

    # --- footer ------------------------------------------------------------
    def test_footer_has_project_name_links_and_copyright(self):
        self.assertContains(self.response, "<footer")
        self.assertContains(self.response, "A student-built learning platform")
        for label in ["Home", "Features", "Login", "Register"]:
            self.assertContains(self.response, f">{label}</a>")
        self.assertContains(self.response, "&copy;")
        self.assertContains(self.response, "Medicaps University")

    # --- responsive and accessible basics -----------------------------------
    def test_page_is_responsive(self):
        self.assertContains(self.response, 'name="viewport"')
        self.assertContains(self.response, 'id="menu-button"')  # menu button for small screens

    def test_page_has_skip_link_and_main_landmark(self):
        self.assertContains(self.response, 'href="#main"')
        self.assertContains(self.response, '<main id="main"')

    def test_page_has_one_h1(self):
        self.assertContains(self.response, "<h1", count=1)

    def test_decorative_icons_are_hidden_from_screen_readers(self):
        self.assertContains(self.response, 'aria-hidden="true"')


class LandingPageForLoggedInStudentTests(TestCase):
    """A logged-in student can still read the page, but gets the dashboard link, not Login."""

    def setUp(self):
        user = User.objects.create_user(email="s@example.com", name="Sam", password="Strong#Pass123")
        self.client.force_login(user)
        self.response = self.client.get(reverse("landing"))

    def test_page_opens(self):
        self.assertEqual(self.response.status_code, 200)

    def test_shows_dashboard_link_instead_of_login_and_get_started(self):
        self.assertContains(self.response, f'href="{reverse("dashboard")}"')
        self.assertNotContains(self.response, f'href="{reverse("login")}"')
        self.assertNotContains(self.response, f'href="{reverse("register")}"')
        self.assertNotContains(self.response, "Get Started")

    def test_still_has_no_private_navigation(self):
        self.assertNotContains(self.response, f'href="{reverse("roadmap")}"')
        self.assertNotContains(self.response, f'action="{reverse("logout")}"')


class SharedDesignSystemTests(TestCase):
    def test_both_layouts_load_the_shared_head(self):
        user = User.objects.create_user(email="s@example.com", name="Sam", password="Strong#Pass123")
        public = self.client.get(reverse("landing"))
        self.client.force_login(user)
        private = self.client.get(reverse("profile"))
        for response in (public, private):
            self.assertContains(response, "css/design-system.css")
            self.assertContains(response, "tailwind.config")
            self.assertContains(response, 'primary: "#172554"')

    def test_design_system_stylesheet_exists(self):
        # (The test client does not serve static files, so we ask Django's finder.)
        from django.contrib.staticfiles import finders

        self.assertIsNotNone(finders.find("css/design-system.css"))

    def test_older_colour_names_still_exist_for_existing_pages(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'violet: "#8B5CF6"')
        self.assertContains(response, 'navy: "#0B1B3A"')

    def test_login_and_register_pages_still_work(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.assertEqual(self.client.get(reverse("register")).status_code, 200)
