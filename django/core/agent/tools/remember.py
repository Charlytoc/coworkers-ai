"""Tool: save a durable long-term memory for the running job / its identity."""

from __future__ import annotations

import logging

from core.agent.base import AgentTool, AgentToolConfig
from core.models import JobAssignment, Memory
from core.services.memory import store_memory

logger = logging.getLogger(__name__)


def make_remember_tool(*, job: JobAssignment) -> AgentToolConfig:
    """Return a ``remember`` tool that persists a memory scoped to this job and its identity."""

    tool = AgentTool(
        type="function",
        name="remember",
        description=(
            "Save a durable memory so you can use it in future runs. Use `core` for stable facts and "
            "preferences you should always keep in mind (e.g. the user's name, tone, timezone); core "
            "memories are automatically added to your context on later runs. Use `knowledge` for "
            "reference details you only need occasionally; retrieve them later with `recall` by topic. "
            "Do not store secrets, tokens, or one-off chatter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The memory text to save.",
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["core", "knowledge"],
                    "default": "knowledge",
                    "description": "`core` = always injected later; `knowledge` = retrieved on demand.",
                },
                "source": {
                    "type": "string",
                    "default": "",
                    "description": "Optional short note on why you're saving this (context/task).",
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional topic tags to make knowledge memories findable via `recall`.",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    )

    def execute(
        content: str,
        memory_type: str = "knowledge",
        source: str = "",
        topics: list[str] | None = None,
    ) -> str:
        if not content.strip():
            return "Error: content is required."
        mtype = (
            Memory.MemoryType.CORE
            if memory_type == "core"
            else Memory.MemoryType.KNOWLEDGE
        )
        try:
            memory = store_memory(
                job=job,
                content=content,
                memory_type=mtype,
                source=source,
                topics=topics or [],
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean message to the agent
            logger.warning("remember tool failed job=%s: %s", job.id, exc)
            return f"Error: could not save memory ({exc})."
        return f"Saved {mtype} memory {memory.id}."

    return AgentToolConfig(tool=tool, function=execute)
