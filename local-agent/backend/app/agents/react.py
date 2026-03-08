"""ReAct Agent Loop

Flow:
1. Receive user message
2. Send to LLM with tool definitions
3. If LLM returns tool_calls -> execute tools -> append results -> goto 2
4. If LLM returns content (finish_reason=stop) -> return final answer
5. Repeat up to max_iterations
6. Each step emits an AgentStep for real-time UI updates via SSE
"""

import json
import logging
from typing import AsyncGenerator

from app.agents.schemas import AgentStep, ToolCall, ToolResult
from app.config import get_settings
from app.llm.client import chat_completion
from app.memory.conversation import Conversation
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


async def run_agent(
    user_message: str,
    conversation: Conversation,
    registry: ToolRegistry,
) -> AsyncGenerator[AgentStep, None]:
    """Execute the ReAct loop, yielding AgentStep events."""
    settings = get_settings()
    conversation.add_user_message(user_message)
    conversation.auto_title(user_message)

    tool_definitions = registry.get_definitions()

    for iteration in range(settings.max_iterations):
        messages = conversation.get_messages_for_api()

        # Call LLM
        try:
            response = await chat_completion(
                messages=messages,
                tools=tool_definitions if tool_definitions else None,
            )
        except Exception as e:
            logger.error("LLM call failed: %s", e, exc_info=True)
            yield AgentStep(type="error", error=f"LLM error: {e}")
            return

        choice = response["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        # Extract reasoning (GPT-OSS specific field)
        reasoning = message.get("reasoning")
        if reasoning:
            yield AgentStep(type="thinking", reasoning=reasoning)

        # Case 1: Tool calls
        if finish_reason == "tool_calls" or message.get("tool_calls"):
            raw_tool_calls = message.get("tool_calls", [])

            # Build tool call entries for conversation history
            api_tool_calls = []
            for tc in raw_tool_calls:
                api_tool_calls.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                })

            conversation.add_tool_call_message(
                content=message.get("content"),
                tool_calls=api_tool_calls,
            )

            # Execute each tool call
            for tc in raw_tool_calls:
                func = tc["function"]
                tool_name = func["name"]
                try:
                    arguments = json.loads(func["arguments"])
                except (json.JSONDecodeError, TypeError):
                    arguments = {}

                tool_call = ToolCall(
                    id=tc["id"],
                    name=tool_name,
                    arguments=arguments,
                )
                yield AgentStep(type="tool_call", tool_call=tool_call)

                # Execute the tool
                result_str = await registry.execute(tool_name, arguments)

                # Truncate long outputs
                if len(result_str) > settings.max_tool_output_chars:
                    result_str = (
                        result_str[: settings.max_tool_output_chars]
                        + "\n... (truncated)"
                    )

                tool_result = ToolResult(
                    tool_call_id=tc["id"],
                    name=tool_name,
                    content=result_str,
                )
                yield AgentStep(type="tool_result", tool_result=tool_result)

                # Add to conversation history
                conversation.add_tool_result_message(
                    tool_call_id=tc["id"],
                    name=tool_name,
                    content=result_str,
                )

            continue  # Next iteration

        # Case 2: Final answer (no tool calls)
        content = message.get("content", "")
        conversation.add_assistant_message(content)
        yield AgentStep(type="answer", content=content)
        return

    # Max iterations reached
    yield AgentStep(
        type="error",
        error=(
            f"Agent reached maximum iterations ({settings.max_iterations}). "
            "Stopping."
        ),
    )
