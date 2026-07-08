"""Select a ``JobAssignment`` for an inbound event/task and build agent loop tools + prompt."""

from __future__ import annotations

import uuid

from core.agent.base import AgentToolConfig
from core.agent.tools.call_artifact_creator import make_call_artifact_creator_tool
from core.agent.tools.create_image_artifact import make_create_image_artifact_tool
from core.agent.tools.create_recurring_job import make_create_recurring_job_tool
from core.agent.tools.create_text_artifact import make_create_text_artifact_tool
from core.agent.tools.instagram_comments import make_instagram_comments_tool
from core.agent.tools.instagram_insights import make_instagram_insights_tool
from core.agent.tools.publish_external_resource import make_publish_external_resource_tool
from core.agent.tools.schedule_one_off_task import make_schedule_one_off_task_tool
from core.agent.tools.send_message import make_send_direct_message_tool, make_send_message_tool
from core.integrations.actionables import (
    ARTIFACTS_CALL_CREATOR,
    ARTIFACTS_CREATE_IMAGE,
    ARTIFACTS_CREATE_TEXT,
    INSTAGRAM_MANAGE_COMMENTS,
    INSTAGRAM_MEDIA_INSIGHTS,
    INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE,
    TASKS_CREATE_RECURRING_JOB,
    TASKS_SCHEDULE_ONE_OFF,
)
from core.integrations.integration_provider_registry import (
    dm_integration_channel,
    inbound_dm_definition,
)
from core.models import Conversation, CyberIdentity, IntegrationAccount, JobAssignment, TaskExecution
from core.schemas.channel import Channel, InstagramDmChannel, TelegramPrivateChannel, WebChatChannel
from core.schemas.job_assignment import JobAssignmentAction, JobAssignmentEventTrigger
from core.services.send_targets import collect_resolved_send_targets, reindex_send_targets


class JobTaskProcessorAgent:
    """Finds runnable jobs for an event and prepares tools + prompt for :class:`core.agent.base.Agent`."""

    @staticmethod
    def build_tools_for_conversation(
        *,
        job: JobAssignment,
        conversation: Conversation,
        task_execution: TaskExecution | None = None,
        actions_override: list[JobAssignmentAction] | None = None,
        task_trigger_type: str = "",
    ) -> list[AgentToolConfig]:
        """Build tool list for an agent run bound to a ``Conversation``.

        The conversation carries the integration account and external thread id when
        ``origin == integration``; :func:`collect_resolved_send_targets` turns that into indexed
        rows for ``send_message`` (reply + web) and ``send_direct_message`` (proactive DMs).
        """
        channel = _channel_for_conversation(conversation)
        return JobTaskProcessorAgent._build_tools_from_actions(
            job=job,
            conversation=conversation,
            channel=channel,
            task_execution=task_execution,
            actions_override=actions_override,
            task_trigger_type=task_trigger_type,
        )

    @staticmethod
    def _build_tools_from_actions(
        *,
        job: JobAssignment,
        conversation: Conversation | None,
        channel: Channel | None,
        task_execution: TaskExecution | None = None,
        actions_override: list[JobAssignmentAction] | None = None,
        task_trigger_type: str = "",
    ) -> list[AgentToolConfig]:
        cfg_model = job.get_config()
        actions = actions_override if actions_override is not None else cfg_model.actions
        tools: list[AgentToolConfig] = []
        seen_names: set[str] = set()

        def _add(cfg: AgentToolConfig) -> None:
            if cfg.tool.name in seen_names:
                return
            seen_names.add(cfg.tool.name)
            tools.append(cfg)

        skip_send_tools = task_trigger_type == "artifact_creator"
        if not skip_send_tools:
            dm_targets = collect_resolved_send_targets(
                job=job,
                conversation=conversation,
                actions=actions,
            )
            reply_like = [t for t in dm_targets if t.target_kind != "direct"]
            direct_only = [t for t in dm_targets if t.target_kind == "direct"]
            if reply_like:
                _add(
                    make_send_message_tool(
                        targets=reindex_send_targets(reply_like),
                        conversation_for_append=conversation,
                    )
                )
            identity = JobTaskProcessorAgent.primary_identity_for_job(job)
            if direct_only and identity is not None:
                _add(
                    make_send_direct_message_tool(
                        targets=reindex_send_targets(direct_only),
                        cyber_identity=identity,
                        conversation_for_append=conversation,
                    )
                )

        publish_actions = [
            act
            for act in actions
            if act.actionable_slug == INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE.slug
        ]
        if publish_actions and task_execution is not None:
            _add(
                make_publish_external_resource_tool(
                    task_execution=task_execution,
                    actions=publish_actions,
                )
            )

        comment_actions = [
            act for act in actions if act.actionable_slug == INSTAGRAM_MANAGE_COMMENTS.slug
        ]
        if comment_actions:
            _add(make_instagram_comments_tool(workspace=job.workspace, actions=comment_actions))

        insight_actions = [
            act for act in actions if act.actionable_slug == INSTAGRAM_MEDIA_INSIGHTS.slug
        ]
        if insight_actions:
            _add(make_instagram_insights_tool(workspace=job.workspace, actions=insight_actions))

        for act in actions:
            slug = act.actionable_slug
            if slug == TASKS_SCHEDULE_ONE_OFF.slug:
                _add(make_schedule_one_off_task_tool(job=job, channel=channel))
            elif slug == TASKS_CREATE_RECURRING_JOB.slug:
                _add(make_create_recurring_job_tool(job=job, channel=channel))
            elif slug == ARTIFACTS_CALL_CREATOR.slug:
                _add(make_call_artifact_creator_tool(job=job, channel=channel))
            elif slug == ARTIFACTS_CREATE_TEXT.slug and task_execution is not None:
                _add(make_create_text_artifact_tool(task_execution=task_execution))
            elif slug == ARTIFACTS_CREATE_IMAGE.slug and task_execution is not None:
                _add(make_create_image_artifact_tool(task_execution=task_execution))
        return tools

    @staticmethod
    def _capability_prompt(actions: list[JobAssignmentAction]) -> str | None:
        action_slugs = {a.actionable_slug for a in actions}
        lines: list[str] = []
        if ARTIFACTS_CALL_CREATOR.slug in action_slugs:
            lines.append(
                "- You can create durable assets by calling `call_artifact_creator`. Use it for "
                "requests to generate images, captions, drafts, or publish-ready content."
            )
        if INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE.slug in action_slugs:
            lines.append(
                "- This job has Instagram publishing rights. If the user asks you to create or publish "
                "an Instagram post, call `call_artifact_creator` and include explicit instructions for "
                "the child task to create the required assets and call `publish_external_resource` with "
                "`resource_type: \"instagram.post\"`. After the child finishes, you will run again to "
                "notify the user."
            )
        if INSTAGRAM_MANAGE_COMMENTS.slug in action_slugs:
            lines.append(
                "- You can read and moderate Instagram comments with `instagram_comments` "
                "(list comments on a post, reply to a post or a specific comment, delete a comment)."
            )
        if INSTAGRAM_MEDIA_INSIGHTS.slug in action_slugs:
            lines.append(
                "- You can read Instagram content and analytics with `instagram_insights` "
                "(list recent media, read per-post reach/likes/comments/saves/shares)."
            )
        if not lines:
            return None
        return (
            "**Current runtime capabilities**\n"
            "These capabilities are authoritative for this run, even if older job instructions mention "
            "outdated tool names or say a capability is unavailable:\n"
            + "\n".join(lines)
        )

    @staticmethod
    def _find_matching_jobs_for_inbound_dm(account: IntegrationAccount) -> list[JobAssignment]:
        spec = inbound_dm_definition(account.provider)
        if spec is None:
            return []
        event_slug = spec.inbound_event_slug
        out: list[JobAssignment] = []
        qs = JobAssignment.objects.filter(workspace=account.workspace, enabled=True, identity__isnull=False).order_by("role_name")
        for job in qs:
            cfg_model = job.get_config()
            listens = any(
                isinstance(tr, JobAssignmentEventTrigger) and tr.on == event_slug
                for tr in cfg_model.triggers
            )
            if not listens:
                continue
            if not any(
                a.integration_account_id == account.id and a.actionable_slug == spec.reply_dm_slug
                for a in cfg_model.actions
            ):
                continue
            out.append(job)
        return out

    @staticmethod
    def find_matching_jobs_for_telegram_private_message(
        account: IntegrationAccount,
    ) -> list[JobAssignment]:
        """Enabled jobs in the workspace that listen for private Telegram messages and include this bot in actions."""
        if account.provider != IntegrationAccount.Provider.TELEGRAM:
            return []
        return JobTaskProcessorAgent._find_matching_jobs_for_inbound_dm(account)

    @staticmethod
    def first_runnable_job_for_telegram_private_message(
        account: IntegrationAccount,
    ) -> JobAssignment | None:
        """Return the first matching job (checks configuration only; does not instantiate tools)."""
        matches = JobTaskProcessorAgent.find_matching_jobs_for_telegram_private_message(account)
        return matches[0] if matches else None

    @staticmethod
    def find_matching_jobs_for_instagram_dm(
        account: IntegrationAccount,
    ) -> list[JobAssignment]:
        """Enabled jobs in the workspace that listen for Instagram DMs and include this account in actions."""
        if account.provider != IntegrationAccount.Provider.INSTAGRAM:
            return []
        return JobTaskProcessorAgent._find_matching_jobs_for_inbound_dm(account)

    @staticmethod
    def first_runnable_job_for_instagram_dm(
        account: IntegrationAccount,
    ) -> JobAssignment | None:
        matches = JobTaskProcessorAgent.find_matching_jobs_for_instagram_dm(account)
        return matches[0] if matches else None

    @staticmethod
    def primary_identity_for_job(job: JobAssignment) -> CyberIdentity | None:
        return job.identity

    @staticmethod
    def integration_channel_for_thread(
        account: IntegrationAccount,
        external_thread_id: str,
    ) -> TelegramPrivateChannel | InstagramDmChannel | None:
        return dm_integration_channel(account, external_thread_id)

    @staticmethod
    def model_for_job(job: JobAssignment) -> str | None:
        """Return the model override from the job's identity config, if set."""
        identity = job.identity
        if identity is None:
            return None
        model = (identity.config or {}).get("model")
        return model.strip() if isinstance(model, str) and model.strip() else None

    @staticmethod
    def _user_facing_send_tool_name(dm_targets: list) -> str | None:
        """Primary user-visible send tool for this run (matches tool registration)."""
        if not dm_targets:
            return None
        has_reply_like = any(getattr(t, "target_kind", None) != "direct" for t in dm_targets)
        has_direct = any(getattr(t, "target_kind", None) == "direct" for t in dm_targets)
        if has_reply_like:
            return "send_message"
        if has_direct:
            return "send_direct_message"
        return None

    @staticmethod
    def build_system_prompt(
        job: JobAssignment,
        *,
        conversation: Conversation | None = None,
        actions_override: list[JobAssignmentAction] | None = None,
    ) -> str:
        cfg_model = job.get_config()
        actions = actions_override if actions_override is not None else cfg_model.actions
        parts = [
            f"You are running the workspace job **{job.role_name}**.",
        ]
        if (job.description or "").strip():
            parts.append(f"Summary:\n{job.description.strip()}")
        if (job.instructions or "").strip():
            parts.append(f"Instructions:\n{job.instructions.strip()}")

        primary = job.identity
        if primary is not None:
            type_label = primary.get_type_display()
            parts.append(
                "**Your persona (stay in character for the user):**\n"
                f"You are **{primary.display_name}** — a **{type_label}** identity in this workspace. "
                "Use this name and voice consistently when you address or represent yourself to the user; "
                "do not fall back to a vague unnamed assistant unless this persona would naturally do so."
            )
        else:
            parts.append(
                "**Persona:** This job has no cyber identity in scope; act as a neutral workspace agent."
            )

        dm_targets = collect_resolved_send_targets(
            job=job,
            conversation=conversation,
            actions=actions,
        )
        if dm_targets:
            reply_like = [t for t in dm_targets if t.target_kind != "direct"]
            direct_only = [t for t in dm_targets if t.target_kind == "direct"]
            if reply_like:
                ri = reindex_send_targets(reply_like)
                pub_lines = "\n".join(
                    f"- {p.target_index}: ({p.target_role}) [{p.integration_type.value}]"
                    for p in (t.to_public() for t in ri)
                )
                parts.append(
                    "**Outbound reply / web targets** (use `send_message` with `target_index` plus `message`):\n"
                    f"{pub_lines}\n"
                    "Do not guess thread or account ids; only the indices above are valid for `send_message`."
                )
            if direct_only:
                di = reindex_send_targets(direct_only)
                pub_direct = "\n".join(
                    f"- {p.target_index}: ({p.target_role}) [{p.integration_type.value}]"
                    for p in (t.to_public() for t in di)
                )
                parts.append(
                    "**Outbound direct DM targets** (use `send_direct_message` with `target_index` plus `message`):\n"
                    f"{pub_direct}\n"
                    "These are allowlisted proactive destinations; only the indices above are valid for "
                    "`send_direct_message`."
                )

        capability_prompt = JobTaskProcessorAgent._capability_prompt(actions)
        if capability_prompt:
            parts.append(capability_prompt)

        tool_name = JobTaskProcessorAgent._user_facing_send_tool_name(dm_targets)
        if tool_name:
            has_direct = any(getattr(t, "target_kind", None) == "direct" for t in dm_targets)
            has_reply_like = any(getattr(t, "target_kind", None) != "direct" for t in dm_targets)
            if has_reply_like and has_direct:
                parts.append(
                    "User-visible text in the **active inbound or web thread** must go through **`send_message`** "
                    "with the correct `target_index` from the reply/web list. Proactive messages to **direct** "
                    "targets must use **`send_direct_message`** with the correct index from the direct list. "
                    "Plain assistant text alone is not delivered on integration channels."
                )
            elif has_direct:
                parts.append(
                    "User-visible text to the configured direct targets must be sent through **`send_direct_message`** "
                    "with the correct `target_index`. Plain assistant text alone is not delivered."
                )
            else:
                parts.append(
                    "Anything the end user must read or hear must be sent through the **`send_message`** "
                    "tool using the correct **`target_index`** from the list above. Plain assistant text "
                    "without that tool is not delivered to the user on this channel. If older job "
                    "instructions refer to `send_chat_message`, treat that as obsolete: the current "
                    "tool name is `send_message`."
                )
        else:
            parts.append(
                "Use the send-message tool attached to this run for user-visible replies; plain assistant "
                "text alone may not reach the user depending on the channel."
            )

        return "\n\n".join(parts)


def _channel_for_conversation(conversation: Conversation) -> Channel | None:
    """Derive a :class:`Channel` from a ``Conversation``."""
    if conversation.origin == Conversation.Origin.WEB:
        cfg = conversation.get_config()
        if cfg.web_user_id is None or cfg.job_assignment_id is None:
            return None
        return WebChatChannel(
            type="web_chat",
            user_id=cfg.web_user_id,
            cyber_identity_id=conversation.cyber_identity_id,
            job_assignment_id=cfg.job_assignment_id,
        )

    account = conversation.integration_account
    if account is None:
        return None

    cfg = conversation.get_config()
    if not cfg.external_thread_id:
        return None

    ch = dm_integration_channel(account, cfg.external_thread_id)
    if ch is not None:
        return ch

    return None
