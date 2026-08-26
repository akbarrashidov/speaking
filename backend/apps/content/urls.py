from django.urls import path

from . import views

urlpatterns = [
    path("topics", views.topics, name="topics"),
    path("topics/<int:topic_id>/material", views.topic_material, name="topic-material"),
]
