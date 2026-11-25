"""Read-only JSON endpoints for the analytics charts (Django REST Framework).

Each endpoint answers GET only, needs a logged-in student and returns only that student's
own data. The numbers come from ChartDataService; nothing is calculated here.
"""

from django.contrib.auth.decorators import login_not_required
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import ChartDataService


class ChartEndpoint(APIView):
    """Base class: GET only (APIView answers other methods with 405)."""

    http_method_names = ["get", "head", "options"]
    section = None  # name of the ChartDataService method

    def get(self, request):
        data = getattr(ChartDataService(), self.section)(request.user)  # request.user: the logged-in student
        return Response(data)


class TrendEndpoint(ChartEndpoint):
    section = "trend"


class TopicsEndpoint(ChartEndpoint):
    section = "topics"


class DifficultyEndpoint(ChartEndpoint):
    section = "difficulty"


# DRF itself refuses anonymous users (HTTP 403 JSON). The page-login middleware is told to let
# the request through so that a script gets a JSON error instead of a redirect to the login page.
trend = login_not_required(TrendEndpoint.as_view())
topics = login_not_required(TopicsEndpoint.as_view())
difficulty = login_not_required(DifficultyEndpoint.as_view())
