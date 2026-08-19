"""
Streaming integration for Coordination System v2.

This module provides streaming event integration for the coordination workflow,
allowing real-time progress updates during multi-agent execution.
"""

from .workflow_events import WorkflowEventEmitter, create_workflow_events

__all__ = [
    "WorkflowEventEmitter",
    "create_workflow_events"
]
