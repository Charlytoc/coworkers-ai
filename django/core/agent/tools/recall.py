"""Tool: search saved knowledge memories for the running job / its identity."""

from __future__ import annotations

import json
import logging

from core.agent.base import AgentTool, AgentToolConfig
from core.models import JobAssignment
from core.services.memory import search_knowledge_memories

logger = logging.getLogger(__name__)


def make_recall_tool(*, job: JobAssignment) -> AgentToolConfig:
    """Return a ``recall`` tool that searches knowledge memories in scope for this job."""

    tool = AgentTool(
        type="function",
        name="recall",
        description=(
            "Search your saved `knowledge` memories by topic and/or text. Returns matching memories "
            "with their content and topics. Core memories are already in your context, so you don't "
            "need to recall those."
        ),
        parameters={
            "type": "object",
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Topic tags to match (any overlap).",
                },
                "query": {
                    "type": "string",
                    "default": "",
                    "description": "Optional text to match within memory content.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    )

    def execute(topics: list[str] | None = None, query: str = "", limit: int = 10) -> str:
        rows = search_knowledge_memories(job=job, topics=topics or [], query=query, limit=limit)
        if not rows:
            return "No matching memories."
        return json.dumps(
            [
                {
                    "id": str(m.id),
                    "content": m.content,
                    "topics": m.topics,
                    "source": m.source,
                    "created": m.created.isoformat(),
                }
                for m in rows
            ]
        )

    return AgentToolConfig(tool=tool, function=execute)
