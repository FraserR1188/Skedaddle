from django.urls import path
from . import views

urlpatterns = [
    path("", views.current_month_redirect, name="home"),
    path("calendar/<int:year>/<int:month>/", views.monthly_calendar, name="monthly_calendar"),
    path("day/<int:year>/<int:month>/<int:day>/", views.daily_rota, name="daily_rota"),
]
