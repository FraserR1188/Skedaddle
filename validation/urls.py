from django.urls import path
from . import views

app_name = "validation"

urlpatterns = [
    path("", views.validation_list, name="list"),
    path("new/", views.validation_create, name="create"),
    path("<int:pk>/edit/", views.validation_update, name="update"),
    path("<int:pk>/delete/", views.validation_delete, name="delete"),
    path("matrix/", views.validation_matrix, name="matrix"),
]
