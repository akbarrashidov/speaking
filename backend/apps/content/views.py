from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.progress import services as progress_services

from .models import ContentStatus, Material, QuestionStatus, Topic, TopicTrack
from .serializers import MaterialSerializer, TopicSerializer


@api_view(["GET"])
def topics(request):
    """GET /api/topics[?track=grammar|phrases] — mavzular + progress statusi.

    Darajalar yo'q: ro'yxat tekis va bitta tartibda. Qaysi mavzu ochiqligini
    faqat progress hal qiladi (§progress.services). `track` berilmasa
    grammatika qaytadi — eski klientlar uchun xatti-harakat o'zgarmaydi.
    """
    track = request.query_params.get("track") or TopicTrack.GRAMMAR
    if track not in TopicTrack.values:
        return Response({"error": "unknown_track"}, status=status.HTTP_400_BAD_REQUEST)

    progress_services.ensure_bootstrapped(request.user)
    items = (
        progress_services.published_topics(track)
        .prefetch_related("related_topics")
        .annotate(
            questions_count=Count("questions", filter=Q(questions__status=QuestionStatus.APPROVED))
        )
    )
    ctx = {"progress_map": progress_services.progress_map(request.user), "request": request}
    return Response({"track": track, "topics": TopicSerializer(items, many=True, context=ctx).data})


@api_view(["GET"])
def topic_material(request, topic_id):
    """GET /api/topics/{id}/material."""
    topic = get_object_or_404(
        Topic.objects.prefetch_related("related_topics"),
        pk=topic_id,
        status=ContentStatus.PUBLISHED,
    )
    material = Material.objects.filter(topic=topic).first()
    if not material:
        return Response({"error": "material_not_found"}, status=status.HTTP_404_NOT_FOUND)
    payload = MaterialSerializer(material, context={"request": request}).data
    payload["accessible"] = progress_services.is_topic_accessible(request.user, topic)
    payload["mode"] = topic.effective_mode
    payload["target_structure"] = topic.target_structure
    return Response(payload)
