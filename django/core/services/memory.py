"""Agent long-term memory: store and retrieve ``Memory`` rows scoped to a job and/or its identity.

Scope rule for a running job: a memory is "in scope" when it is linked to the job itself, OR to the
job's current identity. This preserves memories across an identity swap (job link) while letting an
identity's learnings carry into future jobs (identity link).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.db.models import Q, QuerySet

from core.models import JobAssignment, Memory

logger = logging.getLogger(__name__)

# Keep prompt injection bounded so a large memory set can't blow the context window.
MAX_CORE_MEMORIES_IN_PROMPT = 25
DEFAULT_KNOWLEDGE_SEARCH_LIMIT = 10


def _scope_q(job: JobAssignment) -> Q:
    """Memories linked to this job, or to the job's current identity."""
    q = Q(job_assignment_id=job.id)
    if job.identity_id is not None:
        q |= Q(identity_id=job.identity_id)
    return q


def memories_in_scope_for_job(job: JobAssignment) -> QuerySet[Memory]:
    return Memory.objects.filter(_scope_q(job))


def store_memory(
    *,
    job: JobAssignment,
    content: str,
    memory_type: str = Memory.MemoryType.KNOWLEDGE,
    source: str = "",
    topics: Iterable[str] | None = None,
) -> Memory:
    """Persist a memory, linking it to the running job and its identity (when set)."""
    memory = Memory(
        identity_id=job.identity_id,
        job_assignment=job,
        memory_type=memory_type,
        content=content.strip(),
        source=(source or "").strip(),
        topics=[t.strip() for t in (topics or []) if isinstance(t, str) and t.strip()],
    )
    memory.save()  # full_clean() runs in Memory.save(): validates content + at-least-one-link
    logger.info(
        "memory stored id=%s type=%s job=%s identity=%s topics=%s",
        memory.id, memory.memory_type, job.id, job.identity_id, memory.topics,
    )
    return memory


def core_memories_for_job(job: JobAssignment) -> list[Memory]:
    """CORE memories in scope, newest first, capped for prompt injection."""
    return list(
        memories_in_scope_for_job(job)
        .filter(memory_type=Memory.MemoryType.CORE)
        .order_by("-created")[:MAX_CORE_MEMORIES_IN_PROMPT]
    )


def search_knowledge_memories(
    *,
    job: JobAssignment,
    topics: Iterable[str] | None = None,
    query: str = "",
    limit: int = DEFAULT_KNOWLEDGE_SEARCH_LIMIT,
) -> list[Memory]:
    """Retrieve KNOWLEDGE memories in scope, optionally filtered by topic overlap and/or text match."""
    qs = memories_in_scope_for_job(job).filter(memory_type=Memory.MemoryType.KNOWLEDGE)
    topic_list = [t.strip() for t in (topics or []) if isinstance(t, str) and t.strip()]
    if topic_list:
        topic_q = Q()
        for t in topic_list:
            topic_q |= Q(topics__contains=[t])
        qs = qs.filter(topic_q)
    if query.strip():
        qs = qs.filter(content__icontains=query.strip())
    limit = max(1, min(limit, 50))
    return list(qs.order_by("-created")[:limit])
