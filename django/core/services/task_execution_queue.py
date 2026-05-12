"""Celery enqueue for task executions (isolated to avoid import cycles)."""

from __future__ import annotations

import uuid


def enqueue_task_execution(task_id: uuid.UUID) -> None:
    from core.tasks.task_execution import run_task_execution

    run_task_execution.delay(str(task_id))
