"""Tool: list Instagram media and read per-post insights for the job's Instagram account(s)."""

from __future__ import annotations

import json
import logging

from core.agent.base import AgentTool, AgentToolConfig
from core.models import Workspace
from core.schemas.job_assignment import JobAssignmentAction
from core.services.instagram_graph_api import get_media_insights, list_media

from core.agent.tools.instagram_comments import _resolve_targets

logger = logging.getLogger(__name__)


def make_instagram_insights_tool(
    *,
    workspace: Workspace,
    actions: list[JobAssignmentAction],
) -> AgentToolConfig:
    """Return an ``instagram_insights`` tool bound to the job's Instagram account(s)."""
    targets = _resolve_targets(workspace=workspace, actions=actions)
    by_index = {t.target_index: t for t in targets}
    lines = "\n".join(
        f"- {t.target_index}: [instagram] "
        f"{t.integration_account.display_name or t.integration_account.external_account_id}"
        for t in targets
    )

    tool = AgentTool(
        type="function",
        name="instagram_insights",
        description=(
            "Read the account's Instagram content and analytics. Operations:\n"
            "- `list_media`: list recent posts (id, caption, media_type, timestamp, permalink, "
            "like_count, comments_count). Use these counts to compare post performance without "
            "extra calls.\n"
            "- `insights`: read deeper metrics for one post (requires `media_id`): reach, likes, "
            "comments, saved, shares.\n\n"
            f"Instagram accounts for this run:\n{lines}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["list_media", "insights"]},
                "target_index": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Index of the Instagram account listed in the tool description.",
                },
                "media_id": {"type": "string", "description": "Media id, required for `insights`."},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 25,
                    "description": "Max posts to return for `list_media`.",
                },
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )

    def execute(
        operation: str,
        target_index: int = 0,
        media_id: str = "",
        limit: int = 25,
    ) -> str:
        target = by_index.get(target_index)
        if target is None:
            return f"Error: invalid target_index={target_index}. Valid indices: {sorted(by_index.keys())}."
        account = target.integration_account
        try:
            if operation == "list_media":
                data = list_media(account, limit=limit)
                return json.dumps(data.get("data", data))
            if operation == "insights":
                if not media_id.strip():
                    return "Error: media_id is required for `insights`."
                data = get_media_insights(account, media_id)
                return json.dumps(data.get("data", data))
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Error: unknown operation {operation!r}."

    return AgentToolConfig(tool=tool, function=execute)
