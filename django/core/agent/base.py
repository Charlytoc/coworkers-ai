"""
Base agent classes and interfaces
"""

import json
import logging
import traceback
import uuid
from typing import Dict, List, Any, Callable
from pydantic import BaseModel, Field
from openai.types.responses.response_output_item import ResponseOutputItem
from openai.types.responses.response_input_item import Message, FunctionCallOutput
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_input_text import ResponseInputText
from core.services.openai_service import OpenAIService
from django.conf import settings
from core.schemas.agentic_chat import ExchangeMessage
logger = logging.getLogger(__name__)

_ASSISTANT_HISTORY_DEV_PREFIX = (
    "Prior assistant reply already sent in this Telegram chat:\n"
)


class AgentConfig(BaseModel):
    """Schema for agent configuration"""

    name: str = Field(default="Assistant", description="This is the name of the agent")
    max_iterations: int = Field(
        default=20, description="Maximum iterations for agent loop"
    )
    system_prompt: str = Field(..., description="System prompt for the agent")
    model: str = Field(default="gpt-5.4-mini", description="Model to use for the agent")


class AgentTool(BaseModel):
    """Schema for agent tool definition for Responses API"""

    type: str = Field(default="function", description="Tool type")
    name: str = Field(..., description="Function name")
    description: str = Field(..., description="Function description")
    parameters: Dict[str, Any] = Field(..., description="Function parameters schema")


class AgentToolConfig(BaseModel):
    """Schema for agent tool configuration"""
    tool: AgentTool = Field(..., description="Tool configuration")
    function: Callable = Field(..., description="Function to call to execute the tool")


class AgentLoopSummary(BaseModel):
    """Schema for agent loop summary"""
    messages: List[ExchangeMessage] = Field(..., description="Messages processed in the loop")
    final_response: str = Field("", description="Final response from the agent")
    error: str | None = Field(None, description="Error message if any")
    iterations: int = Field(0, description="Number of agent loop iterations")
    tool_calls_count: int = Field(0, description="Total number of tool calls made")

class Agent:
    """Main agent class for managing functions and OpenAI interactions"""

    def __init__(
        self,
        config: AgentConfig,
        openai_service: OpenAIService | None = None,
    ):
        if not openai_service:
            openai_service = OpenAIService(api_key=settings.OPENAI_API_KEY)
        if not config:
            config = AgentConfig(
                name="Assistant",
                max_iterations=20,
                system_prompt="You are a helpful assistant.",
                model="gpt-4.1-mini",
            )
        self.openai_service = openai_service
        self.config = config

    def _parse_from_exchange_messages(
        self, messages: List[ExchangeMessage]
    ) -> List[Message | ResponseOutputMessage]:
        """Parse exchange messages to OpenAI input items.

        User turns use :class:`Message` (``user`` role). Prior assistant replies are sent as
        :class:`ResponseOutputMessage` (``assistant`` / ``message``) so they match API output shape.
        """
        openai_messages: List[Message | ResponseOutputMessage] = []
        for message in messages:
            raw = message.content
            text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False, default=str)
            if message.role == "user":
                openai_messages.append(
                    Message(
                        role="user",
                        content=[ResponseInputText(text=text, type="input_text")],
                    )
                )
            elif message.role == "assistant":
                openai_messages.append(
                    ResponseOutputMessage(
                        id=f"msg_{uuid.uuid4().hex}",
                        role="assistant",
                        type="message",
                        status="completed",
                        content=[
                            ResponseOutputText(
                                type="output_text",
                                text=text,
                                annotations=[],
                            )
                        ],
                    )
                )
        return openai_messages

    def _parse_to_exchange_messages(self, messages: List[Message | ResponseOutputMessage]) -> List[ExchangeMessage]:
        """Parse OpenAI messages to ExchangeMessages"""
        exchange_messages: List[ExchangeMessage] = []
        for message in messages:
            if message.role == "user":
                exchange_messages.append(ExchangeMessage(
                    role="user",
                    content=message.content[0].text
                ))
            elif message.role == "assistant":
                exchange_messages.append(ExchangeMessage(
                    role="assistant",
                    content=message.content[0].text
                ))
        return exchange_messages

    def _filter_exchange_messages(self, messages: List[Message | FunctionCallOutput | ResponseOutputItem | ResponseOutputMessage]) -> List[ExchangeMessage]:
        """Filter and convert messages to ExchangeMessages, handling all message types.

        Tool calls and their results are kept (as ``tool_call`` / ``tool_result`` entries) so
        ``AgentSessionLog.outputs`` retains a full, debuggable trace of what the agent did during
        the run, not just its user-visible text.
        """
        exchange_messages: List[ExchangeMessage] = []
        for message in messages:
            msg_type = getattr(message, "type", None)
            if msg_type == "function_call":
                try:
                    arguments = json.loads(message.arguments)
                except (TypeError, ValueError):
                    arguments = message.arguments
                exchange_messages.append(ExchangeMessage(
                    role="tool_call",
                    content={
                        "call_id": message.call_id,
                        "name": message.name,
                        "arguments": arguments,
                    },
                ))
            elif msg_type == "function_call_output":
                exchange_messages.append(ExchangeMessage(
                    role="tool_result",
                    content={
                        "call_id": message.call_id,
                        "output": message.output,
                    },
                ))
            elif hasattr(message, 'role') and hasattr(message, 'content'):
                if message.role == "user" and message.content and len(message.content) > 0:
                    exchange_messages.append(ExchangeMessage(
                        role="user",
                        content=message.content[0].text or ""
                    ))
                elif message.role == "assistant" and message.content and len(message.content) > 0:
                    exchange_messages.append(ExchangeMessage(
                        role="assistant",
                        content=message.content[0].text or ""
                    ))
                elif message.role == "developer" and message.content and len(message.content) > 0:
                    raw_dev = message.content[0].text or ""
                    if raw_dev.startswith(_ASSISTANT_HISTORY_DEV_PREFIX):
                        exchange_messages.append(
                            ExchangeMessage(
                                role="assistant",
                                content=raw_dev[len(_ASSISTANT_HISTORY_DEV_PREFIX) :],
                            )
                        )
        return exchange_messages

    def start_agent_loop(
        self,
        messages: List[ExchangeMessage],
        tools: List[AgentToolConfig],
    ) -> AgentLoopSummary:
        """Process message with the agent in a loop until completion"""
        if not self.openai_service:
            raise Exception("❌ OpenAI service not available")

        try:
            # Build a lookup dict: tool name -> callable
            tool_registry: Dict[str, Callable] = {
                tool_config.tool.name: tool_config.function
                for tool_config in tools
            }

            # Prepare messages for OpenAI
            inside_loop_messages: list[
                Message
                | FunctionCallOutput
                | ResponseOutputItem
                | ResponseOutputMessage
            ] = []

            inside_loop_messages.extend(self._parse_from_exchange_messages(messages))

            iteration = 0
            total_tool_calls = 0
            previous_response_id = None

            while iteration < self.config.max_iterations:
                iteration += 1
                logger.info(f"Agent iteration {iteration}")

                # Get response from OpenAI
                response = self.openai_service.create_response(
                    input_data=inside_loop_messages,
                    tools=(
                        [tool.tool.model_dump() for tool in tools]
                        if tools
                        else None
                    ),
                    model=self.config.model,
                    instructions=self.config.system_prompt,
                    store=True,
                    previous_response_id=previous_response_id,
                )

                if not response:
                    logger.error("Error getting response from OpenAI")
                    return AgentLoopSummary(
                        messages=self._filter_exchange_messages(inside_loop_messages),
                        final_response="",
                        error="Error getting response from OpenAI",
                        iterations=iteration,
                        tool_calls_count=total_tool_calls,
                    )

                # Process response items
                function_calls = []
                final_response = ""

                for item in response.output:
                    inside_loop_messages.append(item)
                    if item.type == "message" and item.role == "assistant":
                        # Extract text content from message
                        if item.content:
                            for content_item in item.content:
                                if content_item.text:
                                    final_response = content_item.text or ""
                    elif item.type == "function_call":
                        function_calls.append(item)

                if function_calls:
                    # Process each function call
                    total_tool_calls += len(function_calls)
                    logger.info(f"Processing {len(function_calls)} function calls")

                    for function_call in function_calls:
                        function_name = function_call.name
                        function_args = json.loads(function_call.arguments) or {}
                        call_id = function_call.call_id

                        desc = (
                            f"🔧 Processing tool call for {function_name.replace('_', ' ').title()}"
                        )

                        if (
                            "kwargs" in function_args
                            and function_args["kwargs"]
                            and isinstance(function_args["kwargs"], str)
                        ):
                            kwargs = function_args["kwargs"]
                            if isinstance(kwargs, str):
                                desc += f"\n{kwargs}"
                        else:
                            # Log function execution with truncated arguments
                            args_str = json.dumps(
                                function_args, indent=2, ensure_ascii=False
                            )
                            if len(args_str) > 500:
                                args_preview = args_str[:500] + "... (truncated)"
                            else:
                                args_preview = args_str
                            desc += f"\n{args_preview}"

                        # Execute function
                        if function_name in tool_registry:
                            try:
                                result = tool_registry[function_name](**function_args)
                                result_str = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                                desc += f"\n===Result===\n\n{result_str[:300]}"
                                logger.info(desc)

                                inside_loop_messages.append(
                                    FunctionCallOutput(
                                        call_id=call_id,
                                        output=result_str,
                                        type="function_call_output",
                                    )
                                )

                            except Exception as e:
                                logger.error(f"Error executing function {function_name}: {e}")
                                error_output = f"Error executing {function_name}: {str(e)}"
                                inside_loop_messages.append(
                                    FunctionCallOutput(
                                        call_id=call_id,
                                        output=error_output,
                                        type="function_call_output",
                                    )
                                )
                        else:
                            error_msg = f"Function {function_name} not found"
                            inside_loop_messages.append(
                                FunctionCallOutput(
                                    call_id=call_id,
                                    output=error_msg,
                                    type="function_call_output",
                                )
                            )
                            logger.error(f"Tool not registered: {function_name}")

                    logger.info("Finished processing function calls, continuing loop")

                    # For next iteration, use previous response ID for chaining
                    # TDODO: To use in a future version
                    # previous_response_id = response.id
                else:
                    # No function calls, we have the final response
                    logger.info(f"Final response content: '{final_response}'")

                    # Send final response
                    if final_response:
                        logger.info(f"🤖 {final_response}")

                    return AgentLoopSummary(
                        messages=self._filter_exchange_messages(inside_loop_messages),
                        final_response=final_response,
                        error=None,
                        iterations=iteration,
                        tool_calls_count=total_tool_calls,
                    )

            return AgentLoopSummary(
                messages=self._filter_exchange_messages(inside_loop_messages),
                final_response="",
                error="Maximum iterations reached. Try again.",
                iterations=iteration,
                tool_calls_count=total_tool_calls,
            )

        except Exception as e:
            logger.error(f"Error in agent loop: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            if 'inside_loop_messages' not in locals():
                inside_loop_messages = []
            return AgentLoopSummary(
                messages=self._filter_exchange_messages(inside_loop_messages),
                final_response="",
                error=f"Error in agent: {str(e)}",
                iterations=iteration if 'iteration' in locals() else 0,
                tool_calls_count=total_tool_calls if 'total_tool_calls' in locals() else 0,
            )
