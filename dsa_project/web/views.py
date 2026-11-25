from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from attempts.models import Attempt
from problems.models import Problem
from recommendations.models import Recommendation

from .forms import ProblemFilterForm
from .services import ChartDataService, DashboardService, ProblemListService, RoadmapService
from .submission import SolveTimer, SubmissionError, SubmissionService


@login_not_required  # visitors can open the landing page without an account
def landing(request):
    """Public landing page: explains the project before asking anyone to register."""
    return render(request, "web/landing.html")


def dashboard(request):
    """A quick overview: progress, the newest recommendation and the latest attempts."""
    return render(request, "web/dashboard.html", {"data": DashboardService().get(request.user)})


def problem_list(request):
    """All problems with filters. Each row shows Not attempted / Attempted / Solved."""
    form = ProblemFilterForm(request.GET)
    filters = {}
    if form.is_valid():
        filters = {
            "topic": form.cleaned_data["topic"],
            "subtopic": form.cleaned_data["subtopic"],
            "difficulty": form.cleaned_data["difficulty"],
        }
    # If a filter value is wrong, the error is shown and no filter is applied.
    rows = ProblemListService().get_problems(request.user, **filters)

    context = {
        "form": form,
        "rows": rows,
        "filters_used": any(filters.values()),
    }
    return render(request, "web/problem_list.html", context)


def roadmap(request):
    """Topics and subtopics in order with the student's mastery level."""
    topics = RoadmapService().get_roadmap(request.user)
    return render(request, "web/roadmap.html", {"topics": topics})


@require_GET
def analytics(request):
    """Charts of the student's own performance. The charts load their data from the JSON endpoints."""
    return render(request, "web/analytics.html", {"has_attempts": ChartDataService().has_attempts(request.user)})


@require_GET  # the page only shows data; it has no way to change an attempt
def attempt_history(request, problem_id):
    """The logged-in student's own attempts for one problem, newest first."""
    problem = get_object_or_404(Problem.objects.select_related("subtopic__topic"), pk=problem_id)
    # for_student() always limits the rows to the logged-in student.
    attempts = Attempt.objects.for_student(request.user).filter(problem=problem).order_by("-attempt_no")
    return render(request, "web/attempt_history.html", {"problem": problem, "attempts": attempts})


@require_http_methods(["GET", "POST"])
def problem_detail(request, problem_id):
    """Statement, sample test cases and a code area. POST submits the solution."""
    problem = get_object_or_404(Problem.objects.select_related("subtopic__topic"), pk=problem_id)
    timer = SolveTimer(request.session, problem.pk)

    if request.method == "POST":
        source_code = request.POST.get("source_code", "")
        try:
            attempt = SubmissionService().submit(
                request.user, problem, source_code, opened_at=timer.opened_at()
            )
        except SubmissionError as error:
            messages.error(request, str(error))
            timer.start()  # keep timing: nothing was submitted
            return render(request, "web/problem_detail.html", _problem_context(request, problem, source_code))
        timer.clear()
        # Redirect, so that reloading the page does not submit the same code again.
        return redirect(f"{reverse('problem_detail', args=[problem.pk])}?attempt={attempt.pk}#result")

    timer.start()  # remember when the student opened the page
    attempt = _own_attempt_from_url(request, problem)
    source_code = attempt.source_code if attempt else ""
    return render(request, "web/problem_detail.html", _problem_context(request, problem, source_code, attempt))


def _own_attempt_from_url(request, problem):
    """The attempt named in ?attempt=<id>, but only if it is this student's attempt at this problem."""
    attempt_id = request.GET.get("attempt", "")
    if not attempt_id.isdigit():
        return None
    return Attempt.objects.for_student(request.user).filter(problem=problem, pk=int(attempt_id)).first()


def _problem_context(request, problem, source_code, attempt=None):
    results = []
    recommendation = None
    if attempt:
        results = list(attempt.results.select_related("test_case"))
        # The newest suggestion made for this student (stored right after the submission).
        recommendation = Recommendation.objects.for_student(request.user).select_related("problem", "topic").first()
    return {
        "problem": problem,
        "samples": problem.test_cases.filter(is_sample=True),  # hidden test cases are never shown
        "source_code": source_code,
        "attempt": attempt,
        "results": results,
        "recommendation": recommendation,
        "time_limit": settings.CODE_TIME_LIMIT_SEC,
    }
