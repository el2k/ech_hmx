"""
Celery tasks for async processing.
"""

from .celery_app import celery_app
from .document_processing import process_file_task
from .qa_processing import process_qa_pair_task, process_qa_pairs_batch_task
from .website_crawling import crawl_page_task

__all__ = [
    "celery_app",
    "process_file_task",
    "crawl_page_task",
    "process_qa_pair_task",
    "process_qa_pairs_batch_task",
]
