from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("chores/", views.chore_list, name="chore_list"),
    path("chores/new/", views.chore_new, name="chore_new"),
    path("chores/<int:pk>/edit/", views.chore_edit, name="chore_edit"),
    path("chores/<int:pk>/delete/", views.chore_delete, name="chore_delete"),
    path("chores/<int:pk>/<str:action>/", views.chore_action, name="chore_action"),
    path("members/<int:pk>/", views.member_detail, name="member_detail"),
    path("history/", views.history, name="history"),
    path("whoami/", views.set_actor, name="set_actor"),
]
