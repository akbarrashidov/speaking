"""Shadowing videosi qayerdan kelishi (§apps/content/media.py).

Muhim qoida: YouTube videosi YUKLAB OLINMAYDI. Havola saqlanadi, o'ynatish
YouTube pleyerida bo'ladi — shuning uchun bu yerda tekshiriladigan narsa
havoladan video ID sini to'g'ri ajratib olish.
"""

import pytest

from apps.content.media import media_kind, media_ref, youtube_id
from apps.content.models import Topic, TopicTrack


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
    ],
)
def test_youtube_links_are_recognised(url):
    assert youtube_id(url) == "dQw4w9WgXcQ"
    assert media_kind(url) == "youtube"
    assert media_ref(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.com/clip.mp4",
        "/media/shadowing/lesson.mp4",
        "youtube.com/watch?v=short",
    ],
)
def test_other_links_are_plain_files(url):
    assert youtube_id(url) == ""
    assert media_kind(url) == ("file" if url else "")


@pytest.mark.django_db
def test_topic_reports_the_player_it_needs():
    topic = Topic.objects.create(
        track=TopicTrack.SHADOWING,
        order=1,
        title_uz="Video mashq",
        target_structure="shadow_media_test",
        media_url="https://youtu.be/dQw4w9WgXcQ",
    )
    assert topic.media_kind == "youtube"
    assert topic.media_ref == "dQw4w9WgXcQ"
    # `media_src` — havolaning o'zi: material sahifasida ham ishlatiladi.
    assert topic.media_src == "https://youtu.be/dQw4w9WgXcQ"

    topic.media_url = "https://cdn.example.com/lesson.mp4"
    assert topic.media_kind == "file"
    assert topic.media_ref == "https://cdn.example.com/lesson.mp4"

    topic.media_url = ""
    assert topic.media_kind == ""
    assert topic.media_src == ""
