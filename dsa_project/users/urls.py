from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    # Forgot password
    path("password-reset/", views.password_reset_view, name="password_reset"),
    path("password-reset/sent/", views.password_reset_done_view, name="password_reset_done"),
    path("password-reset/complete/", views.password_reset_complete_view, name="password_reset_complete"),
    path("password-reset/<uidb64>/<token>/", views.password_reset_confirm_view, name="password_reset_confirm"),
]
