"""Pages for registration, login, logout and profile (presentation layer only)."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import (
    LoginView, LogoutView, PasswordResetCompleteView, PasswordResetConfirmView, PasswordResetDoneView,
    PasswordResetView,
)
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import EmailLoginForm, ProfileForm, RegistrationForm, StyledPasswordResetForm, StyledSetPasswordForm


# Every page needs login (see LoginRequiredMiddleware in settings),
# except the two pages marked with @login_not_required / login_not_required(...).
@login_not_required
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your account is created. Please log in.")
        return redirect("login")
    return render(request, "users/register.html", {"form": form})


login_view = login_not_required(
    LoginView.as_view(
        template_name="users/login.html",
        authentication_form=EmailLoginForm,
        redirect_authenticated_user=True,
    )
)

class FriendlyLogoutView(LogoutView):
    """Django's LogoutView accepts POST only, which protects against logout by link.
    After logging out the student lands on the public page with a short message."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.success(request, "You have been logged out.")
        return response


logout_view = FriendlyLogoutView.as_view()


# ---------------------------------------------------------------- forgot password
class ConsoleEmailNoticeMixin:
    """Tells the page when e-mail is only printed in the server terminal (the default here)."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["console_email"] = settings.EMAIL_BACKEND.endswith(("console.EmailBackend", "ReadableConsoleEmailBackend"))
        return context


class PasswordResetRequestView(ConsoleEmailNoticeMixin, PasswordResetView):
    template_name = "users/password_reset_form.html"
    email_template_name = "users/password_reset_email.txt"
    subject_template_name = "users/password_reset_subject.txt"
    form_class = StyledPasswordResetForm
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        self.extra_email_context = {"hours": settings.PASSWORD_RESET_TIMEOUT // 3600}
        return super().form_valid(form)


class PasswordResetSentView(ConsoleEmailNoticeMixin, PasswordResetDoneView):
    template_name = "users/password_reset_done.html"


class PasswordResetChooseView(PasswordResetConfirmView):
    template_name = "users/password_reset_confirm.html"
    form_class = StyledSetPasswordForm
    success_url = reverse_lazy("password_reset_complete")


class PasswordResetFinishedView(PasswordResetCompleteView):
    template_name = "users/password_reset_complete.html"


# Visitors who forgot their password are not logged in, so all four pages are public.
password_reset_view = login_not_required(PasswordResetRequestView.as_view())
password_reset_done_view = login_not_required(PasswordResetSentView.as_view())
password_reset_confirm_view = login_not_required(PasswordResetChooseView.as_view())
password_reset_complete_view = login_not_required(PasswordResetFinishedView.as_view())


def profile(request):
    """Show the logged-in student's own details and let them edit name and e-mail."""
    form = ProfileForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile is updated.")
        return redirect("profile")
    return render(request, "users/profile.html", {"form": form})
