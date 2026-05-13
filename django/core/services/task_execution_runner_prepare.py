"""Build agent loop messages and system prompt for a task execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.models import Conversation, JobAssignment, TaskExecution
from core.schemas.agentic_chat import ExchangeMessage
from core.schemas.job_assignment import JobAssignmentAction
from core.schemas.task_execution import TaskExecutionInputs
from core.services.conversations import append_user_message, prior_exchange_messages
from core.services.job_task_processor_agent import JobTaskProcessorAgent


@dataclass(frozen=True)
class PreparedAgentLoop:
    loop_messages: list[ExchangeMessage]
    system_prompt: str
    actions_override: list[JobAssignmentAction] | None


def _trigger_is_event(trigger: dict[str, Any] | None) -> bool:
    if not trigger:
        return False
    return trigger.get("type") == "event"


def _trigger_type(trigger: dict[str, Any] | None) -> str:
    if not trigger:
        return ""
    return str(trigger.get("type") or "")


def prepare_agent_loop(
    *,
    task: TaskExecution,
    job: JobAssignment,
    conversation: Conversation,
    inputs: TaskExecutionInputs,
) -> tuple[PreparedAgentLoop | None, str | None]:
    trigger_dict = inputs.trigger if isinstance(inputs.trigger, dict) else None
    trigger_type = _trigger_type(trigger_dict)
    is_event = _trigger_is_event(trigger_dict)
    actions_override = inputs.actions if inputs.actions else None

    if trigger_type == "artifact_creator_completed":
        loop_messages = prior_exchange_messages(conversation)
        task_msg = ExchangeMessage(role="user", content=inputs.task_instructions)
        loop_messages = [*loop_messages, task_msg] if loop_messages else [task_msg]
        system_prompt = (
            JobTaskProcessorAgent.build_system_prompt(
                job,
                conversation=conversation,
                actions_override=actions_override,
            )
            + "\n\nAn artifact creator task has finished in the background. The user message above "
            "includes whether it succeeded or failed and any artifact JSON or error details. "
            "Notify the user naturally through the appropriate send tool: on success, briefly "
            "celebrate or summarize what was produced; on failure, apologize and explain. "
            "Do not create new artifacts unless the user explicitly asks for changes."
        )
        return PreparedAgentLoop(loop_messages, system_prompt, actions_override), None

    if trigger_type == "artifact_creator":
        loop_messages = prior_exchange_messages(conversation)
        task_msg = ExchangeMessage(role="user", content=inputs.task_instructions)
        loop_messages = [*loop_messages, task_msg] if loop_messages else [task_msg]
        system_prompt = (
            JobTaskProcessorAgent.build_system_prompt(
                job,
                conversation=conversation,
                actions_override=actions_override,
            )
            + "\n\nThis run is an artifact creator task. You do not have send_message or "
            "send_direct_message here; do not try to notify the user from this run. "
            "Create durable artifacts that satisfy the latest instructions using the artifact tools "
            "(and publish_external_resource when publishing to Instagram is in scope). "
            "Prefer saving useful output through the artifact tools; do not treat plain final text "
            "as the saved artifact. When you finish, the parent job will run again automatically "
            "to message the user."
        )
        return PreparedAgentLoop(loop_messages, system_prompt, actions_override), None

    if is_event:
        loop_messages = prior_exchange_messages(conversation)
        if not loop_messages:
            return None, "empty_conversation"
        system_prompt = JobTaskProcessorAgent.build_system_prompt(
            job,
            conversation=conversation,
            actions_override=actions_override,
        )
        return PreparedAgentLoop(loop_messages, system_prompt, actions_override), None

    append_user_message(
        conversation,
        content_text=inputs.task_instructions,
        content_structured={"trigger": "task_execution", "task_execution_id": str(task.id)},
    )
    system_prompt = (
        JobTaskProcessorAgent.build_system_prompt(
            job,
            conversation=conversation,
            actions_override=actions_override,
        )
        + "\n\nYou are executing a deferred task created earlier. Use the tools "
        "to complete the instructions below. When you are done, output a brief confirmation."
    )
    loop_messages = [ExchangeMessage(role="user", content=inputs.task_instructions)]
    return PreparedAgentLoop(loop_messages, system_prompt, actions_override), None


def trigger_meta(inputs: TaskExecutionInputs) -> tuple[dict[str, Any] | None, str, bool]:
    trigger_dict = inputs.trigger if isinstance(inputs.trigger, dict) else None
    return trigger_dict, _trigger_type(trigger_dict), _trigger_is_event(trigger_dict)
