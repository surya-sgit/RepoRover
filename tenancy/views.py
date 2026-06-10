"""GitHub OAuth dashboard & BYOK key-vault UI (PRD §3.1, §6.1).

Auth is GitHub-OAuth only. The dashboard lets a user attach BYOK secrets
(encrypted at rest) and configure per-repo behaviour. Repo behaviour is read
from these DB records only — never from files inside a PR (PRD §6.1).
"""
from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import github_oauth
from .forms import ByokKeyForm, RepoSettingsForm
from .models import OrganizationConfig, RepoSettings

SESSION_TOKEN = "gh_oauth_token"
SESSION_LOGIN = "gh_login"
SESSION_STATE = "gh_oauth_state"
SESSION_INSTALLS = "gh_installation_ids"


def _require_login(request):
    return bool(request.session.get(SESSION_TOKEN))


def _redirect_uri(request):
    return request.build_absolute_uri(reverse("tenancy:callback"))


def login(request):
    state = secrets.token_urlsafe(16)
    request.session[SESSION_STATE] = state
    return redirect(github_oauth.authorize_url(state, _redirect_uri(request)))


def callback(request):
    if request.GET.get("state") != request.session.get(SESSION_STATE):
        return HttpResponseForbidden("OAuth state mismatch")
    code = request.GET.get("code")
    if not code:
        return HttpResponseForbidden("Missing OAuth code")

    token = github_oauth.exchange_code_for_token(code, _redirect_uri(request))
    request.session[SESSION_TOKEN] = token
    request.session[SESSION_LOGIN] = github_oauth.get_user_login(token)
    # Record which installations this user may administer (authorization scope).
    installs = github_oauth.list_user_installations(token)
    request.session[SESSION_INSTALLS] = [int(i["id"]) for i in installs]
    return redirect("tenancy:dashboard")


def logout(request):
    request.session.flush()
    return redirect("tenancy:login")


def setup(request):
    """GitHub App post-install redirect: capture installation_id (PRD §3.1)."""
    installation_id = request.GET.get("installation_id")
    if installation_id:
        OrganizationConfig.objects.get_or_create(
            github_installation_id=int(installation_id)
        )
        # Allow administering this installation in the current session.
        installs = set(request.session.get(SESSION_INSTALLS, []))
        installs.add(int(installation_id))
        request.session[SESSION_INSTALLS] = list(installs)
        messages.success(request, "RepoRover installed. Configure your keys below.")
    return redirect("tenancy:dashboard")


def dashboard(request):
    if not _require_login(request):
        return redirect("tenancy:login")

    allowed = set(request.session.get(SESSION_INSTALLS, []))
    # Surface only installations the OAuth'd user is authorized for.
    orgs = OrganizationConfig.objects.filter(github_installation_id__in=allowed)
    return render(
        request,
        "tenancy/dashboard.html",
        {"login": request.session.get(SESSION_LOGIN), "orgs": orgs},
    )


def _authorize_org(request, org: OrganizationConfig):
    allowed = set(request.session.get(SESSION_INSTALLS, []))
    return org.github_installation_id in allowed


def org_keys(request, org_id: int):
    if not _require_login(request):
        return redirect("tenancy:login")
    org = get_object_or_404(OrganizationConfig, pk=org_id)
    if not _authorize_org(request, org):
        return HttpResponseForbidden("Not authorized for this installation")

    if request.method == "POST":
        form = ByokKeyForm(request.POST)
        if form.is_valid():
            gem = form.cleaned_data["gemini_api_key"]
            e2b = form.cleaned_data["e2b_api_key"]
            if gem:
                org.set_gemini_key(gem)
            if e2b:
                org.set_e2b_key(e2b)
            org.save()
            messages.success(request, "Keys saved (encrypted).")
            return redirect("tenancy:dashboard")
    else:
        form = ByokKeyForm()

    return render(request, "tenancy/org_keys.html", {"org": org, "form": form})


def repo_settings(request, org_id: int):
    if not _require_login(request):
        return redirect("tenancy:login")
    org = get_object_or_404(OrganizationConfig, pk=org_id)
    if not _authorize_org(request, org):
        return HttpResponseForbidden("Not authorized for this installation")

    if request.method == "POST":
        form = RepoSettingsForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.org_config = org
            obj.save()
            messages.success(request, f"Saved settings for {obj.repository_name}.")
            return redirect("tenancy:repo_settings", org_id=org.pk)
    else:
        form = RepoSettingsForm()

    return render(
        request,
        "tenancy/repo_settings.html",
        {"org": org, "form": form, "repos": org.repos.all()},
    )
