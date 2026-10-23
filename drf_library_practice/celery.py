import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "drf_library_practice.settings")

app = Celery("drf_library_practice")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()
