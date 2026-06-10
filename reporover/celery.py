"""Celery application bootstrap for RepoRover.

Workers run the long-running LangGraph agent pipeline off the request thread so
the webhook endpoint can return HTTP 200 within GitHub's 10-second budget
(PRD §3.3). Start a worker with:

    celery -A reporover worker -l info
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "reporover.settings")

app = Celery("reporover")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
