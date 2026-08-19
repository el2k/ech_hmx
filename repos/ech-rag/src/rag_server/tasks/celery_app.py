"""
Celery application configuration.

This module configures Celery for async document processing tasks.
It includes signal handlers to properly manage database connections
across forked worker processes.
"""

from celery import Celery
from celery.signals import worker_process_init, task_prerun

from ..config import get_settings

# Get settings
settings = get_settings()

# Create Celery app
# 创建celery
celery_app = Celery(
    "rag_service",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "src.rag_service.tasks.document_processing",
        "src.rag_service.tasks.maintenance",
        "src.rag_service.tasks.website_crawling",
        "src.rag_service.tasks.qa_processing",
    ]
)

# Configure Celery
celery_app.conf.update(
    task_serializer=settings.celery_task_serializer, # 指定任务序列化器，默认json
    result_serializer=settings.celery_result_serializer, # 指定结果序列化器，默认json
    accept_content=["json"], # 接受的内容类型，默认json
    result_expires=3600, # 结果过期时间，单位秒，默认3600秒
    timezone=settings.celery_timezone,# 时区设置，默认UTC
    enable_utc=True, # 启用UTC时间，默认True
    task_track_started=True, # 追踪任务启动状态，默认False
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1, # 工作进程预取任务数，默认4
    worker_max_tasks_per_child=1000, # 每个工作进程最大任务数，默认无限制
)

# Task routing
# 配置任务路由，将不同类型的任务分配到不同的队列中，以便更好地管理和调度任务。
celery_app.conf.task_routes = {
    "src.rag_service.tasks.document_processing.*": {"queue": "document_processing"},
    "src.rag_service.tasks.embedding.*": {"queue": "embedding"},
    "src.rag_service.tasks.website_crawling.*": {"queue": "website_crawling"},
    "src.rag_service.tasks.qa_processing.*": {"queue": "qa_processing"},
    "crawl_page_task": {"queue": "celery"},  # Single page crawl task
    "process_qa_pair_task": {"queue": "celery"},  # Default queue for QA tasks
    "process_qa_pairs_batch_task": {"queue": "celery"},
}

# Task rate limits
# This controls how many tasks of each type can be executed per time unit
# Format: "n/s" (per second), "n/m" (per minute), "n/h" (per hour)
# 配置任务速率限制，控制每种类型的任务在单位时间内可以执行的次数，以防止过载。
celery_app.conf.task_annotations = {
    # Limit crawl tasks to prevent overwhelming target sites and system resources
    # 60 pages per minute = ~1 page every 1 seconds
    "crawl_page_task": {
        "rate_limit": "60/m",
    },
    # Document processing can be more aggressive since it's internal processing
    "process_file_task": {
        "rate_limit": "60/m",
    },
}

# Beat schedule for periodic tasks
# 配置定期任务调度，使用Celery Beat来定期执行维护任务，例如清理失败的任务。
celery_app.conf.beat_schedule = {
    "cleanup-failed-tasks": {
        "task": "src.rag_service.tasks.maintenance.cleanup_failed_tasks",
        "schedule": 3600.0,  # Every hour
    },
}


'''用于在分叉工作进程管理数据库连接的信号处理程序
旧的连接将在该事件循环关闭后失败，并抛出以下错误:
问题:Celer的prefok模式会分叉工作进程。当使用SQLAlchemy时，数据库连接被绑定到特定的事件循环上。如果在某个任务中创建了连接，则新任务将创建一个新的事件循环，
#在异步引擎中，数据库连接绑定到特定的事件循环。
#如果在一个任务中创建了连接，则事件循环会关闭，并且一个
#新任务创建新的事件循环，旧连接将报错:
“运行时错误:事件循环已关闭”
“Future附加到不同的循环”
#解决方案:在初始化工作进程时重置数据库状态，并确保每个任务运行前都重新设置干净的连接。
#在每个任务运行前，以确保连接干净。'''
# worker_process_init.connect: 这个信号在每个工作进程初始化时触发。它确保每个工作进程在启动时都有一个干净的数据库状态，避免继承父进程的连接。
@worker_process_init.connect
def on_worker_process_init(**kwargs):
    """
    Called when a worker process is initialized (after fork).
    
    This ensures each worker starts with a clean database state,
    avoiding inherited connections from the parent process.
    """
    from ..database import reset_db_state
    reset_db_state()


# task_prerun.connect: 这个信号在每个任务执行前触发。它确保在运行任何任务之前，数据库连接都会被重置，从而防止在任务创建新事件循环时出现“Future attached to a different loop”错误。
@task_prerun.connect
def on_task_prerun(task_id, task, args, kwargs, **rest):
    """
    Called before each task is executed.
    
    This ensures database connections are reset before running any task,
    preventing 'Future attached to a different loop' errors when tasks
    create new event loops.
    """
    from ..database import reset_db_state
    reset_db_state()
