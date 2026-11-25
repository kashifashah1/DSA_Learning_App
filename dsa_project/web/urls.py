from django.urls import path

from . import api, views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("problems/", views.problem_list, name="problems"),
    path("problems/<int:problem_id>/", views.problem_detail, name="problem_detail"),
    path("problems/<int:problem_id>/attempts/", views.attempt_history, name="attempt_history"),
    path("roadmap/", views.roadmap, name="roadmap"),
    path("analytics/", views.analytics, name="analytics"),
    # Read-only JSON for the charts (own data only)
    path("api/analytics/trend/", api.trend, name="api_trend"),
    path("api/analytics/topics/", api.topics, name="api_topics"),
    path("api/analytics/difficulty/", api.difficulty, name="api_difficulty"),
]
