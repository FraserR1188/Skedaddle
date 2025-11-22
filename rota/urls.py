from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("calendar/<int:year>/<int:month>/", views.monthly_calendar, name="monthly_calendar"),
    path("day/<int:year>/<int:month>/<int:day>/", views.daily_rota, name="daily_rota"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/add/", views.staff_create, name="staff_create"),
]
