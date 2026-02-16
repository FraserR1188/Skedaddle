from django.urls import path
from . import views

app_name = "validation"

urlpatterns = [
    path("", views.validation_list, name="list"),
    path("new/", views.validation_create, name="create"),
    path("<int:pk>/edit/", views.validation_update, name="update"),
    path("<int:pk>/delete/", views.validation_delete, name="delete"),
    path("matrix/", views.validation_matrix, name="matrix"),
    path("cards/", views.validation_cards, name="validation_cards"),
    path("quick-update/", views.validation_quick_update,
         name="validation_quick_update"),
]
