"""Celery beat dispatchers: move due ``TaskExecution``s to the runner + fire cron ``JobAssignment``s."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
from django.db.models import Q

from core.models import JobAssignment, TaskExecution
from core.schemas.job_assignment import JobAssignmentCronTrigger
from core.schemas.task_execution import TaskExecutionInputs
from core.tasks.task_execution import run_task_execution

logger = get_task_logger(__name__)

# Cap to avoid unbounded scan per beat tick.
MAX_TASKS_PER_TICK = 200
MAX_JOBS_PER_TICK = 200


@shared_task
def dispatch_due_task_executions() -> dict:
    """Queue every PENDING ``TaskExecution`` whose ``scheduled_to`` is due."""
    now = datetime.now(timezone.utc)
    pending_qs = (
        TaskExecution.objects.filter(
            status=TaskExecution.Status.PENDING,
            requires_approval=False,
        )
        .filter(Q(scheduled_to__isnull=True) | Q(scheduled_to__lte=now))
        .order_by("scheduled_to", "created")
    )[:MAX_TASKS_PER_TICK]

    dispatched = 0
    for task in pending_qs:
        with transaction.atomic():
            updated = TaskExecution.objects.filter(
                id=task.id, status=TaskExecution.Status.PENDING
            ).update(status=TaskExecution.Status.QUEUED)
            if not updated:
                continue
            run_task_execution.delay(str(task.id))
            dispatched += 1

    if dispatched:
        logger.info("dispatch_due_task_executions: queued %s task(s)", dispatched)
    return {"dispatched": dispatched}


@shared_task
def dispatch_due_cron_jobs() -> dict:
    """For each enabled cron ``JobAssignment``, create a new ``TaskExecution`` when the schedule ticks.

    Fires at most once per tick per job. Rough semantics: if the most recent execution is older
    than the cron's previous trigger time, create a fresh ``TaskExecution`` with ``scheduled_to=now()``
    and let :func:`dispatch_due_task_executions` pick it up on the next tick.
    """
    try:
        from croniter import croniter
    except ImportError:
        logger.warning("dispatch_due_cron_jobs: croniter not installed, skipping.")
        return {"dispatched": 0}

    now = datetime.now(timezone.utc)
    jobs = (
        JobAssignment.objects.filter(enabled=True)
        .select_related("workspace")
        .order_by("id")[:MAX_JOBS_PER_TICK]
    )

    dispatched = 0
    for job in jobs:
        try:
            cfg = job.get_config()
        except Exception:
            logger.exception("dispatch_due_cron_jobs: invalid config on job=%s", job.id)
            continue

        cron_exprs = [
            tr.on for tr in cfg.triggers if isinstance(tr, JobAssignmentCronTrigger) and tr.on
        ]
        if not cron_exprs:
            continue

        for expr in cron_exprs:
            if not croniter.is_valid(expr):
                continue
            # Use the last execution (for this job) as the reference point.
            last_run_at = (
                TaskExecution.objects.filter(job_assignment=job)
                .exclude(status=TaskExecution.Status.CANCELLED)
                .order_by("-created")
                .values_list("created", flat=True)
                .first()
            )
            # Anchor at job creation (or 7 days ago) if no prior run — avoids flooding old jobs.
            anchor = last_run_at or max(job.created, now - timedelta(days=7))
            itr = croniter(expr, anchor)
            next_fire = itr.get_next(datetime)
            if next_fire.tzinfo is None:
                next_fire = next_fire.replace(tzinfo=timezone.utc)
            if next_fire > now:
                continue

            _create_cron_task(job, cfg, expr)
            dispatched += 1
            break  # one fire per job per tick

    if dispatched:
        logger.info("dispatch_due_cron_jobs: created %s task(s)", dispatched)
    return {"dispatched": dispatched}


def _create_cron_task(job: JobAssignment, cfg, cron_expr: str) -> None:
    channel = cfg.channels[0] if cfg.channels else None
    identity_snapshot = None
    if job.identity_id is not None:
        from core.schemas.task_execution import IdentityConfigSnapshot
        identity = job.identity
        identity_snapshot = IdentityConfigSnapshot(identity=identity.id, config=identity.config or {})

    inputs = TaskExecutionInputs(
        task_instructions=job.instructions or job.role_name,
        parent_job_assignment=job.id,
        identity_config=identity_snapshot,
        channel=channel,
        trigger={"type": "cron", "cron": cron_expr},
    )
    with transaction.atomic():
        task = TaskExecution(
            workspace=job.workspace,
            job_assignment=job,
            status=TaskExecution.Status.PENDING,
            scheduled_to=datetime.now(timezone.utc),
        )
        task.set_inputs(inputs)
        task.save()
    logger.info("dispatch_due_cron_jobs: created task=%s for job=%s cron=%r", task.id, job.id, cron_expr)
