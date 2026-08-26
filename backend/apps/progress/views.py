from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.content.models import LEARNER_TRACKS, localized

from . import report as report_mod
from . import services
from .models import ErrorLog, TopicProgress


@api_view(["GET"])
def progress(request):
    """GET /api/progress — grammatik mavzular bo'yicha progress."""
    user = request.user
    services.ensure_bootstrapped(user)
    language = user.language_code or ""

    # Daraja aniqlash mavzusi bu yerda YO'Q: u dars emas, bir martalik o'lchov.
    # Progressda ko'rinsa o'quvchi uni o'tilmagan mavzu deb o'ylardi.
    rows = (
        TopicProgress.objects.filter(user=user, topic__track__in=LEARNER_TRACKS)
        .select_related("topic")
        .order_by("topic__track", "topic__order")
    )
    items = [
        {
            "topic_id": r.topic_id,
            "track": r.topic.track,
            "order": r.topic.order,
            "title": localized(r.topic, "title", language),
            "status": r.status,
            "sessions_count": r.sessions_count,
            "last_accuracy": r.last_accuracy,
            "best_accuracy": r.best_accuracy,
        }
        for r in rows
    ]

    active = next((i for i in items if i["status"] == "active"), None)
    pending_errors = ErrorLog.objects.filter(user=user, resolved=False).count()

    return Response(
        {
            "topics": items,
            "active_topic_id": active["topic_id"] if active else None,
            "open_errors": pending_errors,
        }
    )


@api_view(["GET"])
def progress_report(request):
    """GET /api/progress/report — sessiyalararo umumiy xato tahlili (§Faza 7).

    Agregatsiya SQL'da (tekin), o'zbekcha matn bitta arzon LLM chaqiruvida va
    keshlanadi — ma'lumot o'zgarmasa qayta chaqirilmaydi.
    """
    return Response(report_mod.build(request.user, refresh=request.query_params.get("refresh")))
