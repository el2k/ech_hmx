from celery import Celery
from app.config import settings

celery_app = Celery(
    "workflow_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["celery_app.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_soft_time_limit=300,  # 5 minutes
    task_time_limit=360,       # 6 minutes
    task_default_queue="workflow",
    task_routes={
        "celery_app.tasks.*": {"queue": "workflow"},
    },
)

