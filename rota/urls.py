from django.urls import path
from . import views

urlpatterns = [
    path("", views.todays_rota, name="todays_rota"),
]
