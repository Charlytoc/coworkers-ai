"""Tool: read, reply to, and delete Instagram comments for the job's Instagram account(s)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from core.agent.base import AgentTool, AgentToolConfig
from core.models import IntegrationAccount, Workspace
from core.schemas.job_assignment import JobAssignmentAction
from core.services.instagram_graph_api import (
    delete_comment,
    list_comments,
    reply_to_comment,
    reply_to_comment_thread,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _AccountTarget:
    target_index: int
    integration_account: IntegrationAccount


def _resolve_targets(
    *, workspace: Workspace, actions: list[JobAssignmentAction]
) -> list[_AccountTarget]:
    targets: list[_AccountTarget] = []
    seen: set[str] = set()
    for action in actions:
        account_id = action.integration_account_id
        if account_id is None or str(account_id) in seen:
            continue
        account = IntegrationAccount.objects.filter(
            id=account_id,
            workspace=workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
        ).first()
        if account is None:
            continue
        seen.add(str(account_id))
        targets.append(_AccountTarget(target_index=len(targets), integration_account=account))
    return targets


def make_instagram_comments_tool(
    *,
    workspace: Workspace,
    actions: list[JobAssignmentAction],
) -> AgentToolConfig:
    """Return an ``instagram_comments`` tool bound to the job's Instagram account(s)."""
    targets = _resolve_targets(workspace=workspace, actions=actions)
    by_index = {t.target_index: t for t in targets}
    lines = "\n".join(
        f"- {t.target_index}: [instagram] "
        f"{t.integration_account.display_name or t.integration_account.external_account_id}"
        for t in targets
    )

    tool = AgentTool(
        type="function",
        name="instagram_comments",
        description=(
            "Manage comments on the account's Instagram media. Operations:\n"
            "- `list`: list comments on a post (requires `media_id`).\n"
            "- `reply_to_media`: add a top-level comment on a post (requires `media_id` + `message`).\n"
            "- `reply_to_comment`: reply under an existing comment (requires `comment_id` + `message`).\n"
            "- `delete`: delete a comment (requires `comment_id`).\n\n"
            f"Instagram accounts for this run:\n{lines}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "reply_to_media", "reply_to_comment", "delete"],
                },
                "target_index": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Index of the Instagram account listed in the tool description.",
                },
                "media_id": {"type": "string", "description": "Media id, for `list` / `reply_to_media`."},
                "comment_id": {
                    "type": "string",
                    "description": "Comment id, for `reply_to_comment` / `delete`.",
                },
                "message": {"type": "string", "description": "Reply text, for reply operations."},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )

    def execute(
        operation: str,
        target_index: int = 0,
        media_id: str = "",
        comment_id: str = "",
        message: str = "",
    ) -> str:
        target = by_index.get(target_index)
        if target is None:
            return f"Error: invalid target_index={target_index}. Valid indices: {sorted(by_index.keys())}."
        account = target.integration_account
        try:
            if operation == "list":
                if not media_id.strip():
                    return "Error: media_id is required for `list`."
                data = list_comments(account, media_id)
                return json.dumps(data.get("data", data))
            if operation == "reply_to_media":
                if not media_id.strip() or not message.strip():
                    return "Error: media_id and message are required for `reply_to_media`."
                data = reply_to_comment(account, media_id, message)
                return json.dumps(data)
            if operation == "reply_to_comment":
                if not comment_id.strip() or not message.strip():
                    return "Error: comment_id and message are required for `reply_to_comment`."
                data = reply_to_comment_thread(account, comment_id, message)
                return json.dumps(data)
            if operation == "delete":
                if not comment_id.strip():
                    return "Error: comment_id is required for `delete`."
                data = delete_comment(account, comment_id)
                return json.dumps(data)
        except ValueError as exc:
            return f"Error: {exc}"
        return f"Error: unknown operation {operation!r}."

    return AgentToolConfig(tool=tool, function=execute)
