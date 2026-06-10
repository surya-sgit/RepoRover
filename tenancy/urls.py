from django.urls import path

from . import views

app_name = "tenancy"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.login, name="login"),
    path("callback/", views.callback, name="callback"),
    path("logout/", views.logout, name="logout"),
    path("setup/", views.setup, name="setup"),
    path("org/<int:org_id>/keys/", views.org_keys, name="org_keys"),
    path("org/<int:org_id>/repos/", views.repo_settings, name="repo_settings"),
]
