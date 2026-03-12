"""ReAct Agent Loop

Flow:
1. Receive user message
2. Send to LLM with tool definitions
3. If LLM returns tool_calls -> execute tools -> append results -> goto 2
4. If LLM returns content (finish_reason=stop) -> return final answer
5. Repeat up to max_iterations
6. Each step emits an AgentStep for real-time UI updates via SSE

During LLM calls, a monitor task polls model-router for switching progress
and emits "switching" events so the UI can show real-time status.
"""

import asyncio
import json
import logging
from typing import Any, AsyncGenerator

from app.agents.schemas import AgentStep, SwitchingInfo, ToolCall, ToolResult
from app.config import get_settings
from app.llm.client import chat_completion, get_router_status
from app.memory.conversation import Conversation
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Phase labels for UI display
_PHASE_MESSAGES: dict[str, str] = {
    "stopping_vllm": "vLLM を停止中...",
    "loading_ollama": "Ollama モデルをロード中...",
    "unloading_ollama": "Ollama モデルをアンロード中...",
    "starting_vllm": "vLLM を起動中...",
    "idle": "準備完了",
}


async def run_agent(
    user_message: str,
    conversation: Conversation,
    registry: ToolRegistry,
    model: str | None = None,
    cancel_event: asyncio.Event | None = None,
) -> AsyncGenerator[AgentStep, None]:
    """Execute the ReAct loop, yielding AgentStep events."""
    settings = get_settings()
    conversation.add_user_message(user_message)
    conversation.auto_title(user_message)

    tool_definitions = registry.get_definitions()
    max_iter = settings.max_iterations

    for iteration in range(max_iter):
        # Check cancellation at start of each iteration
        if cancel_event and cancel_event.is_set():
            yield AgentStep(type="cancelled", content="Agent stopped by user.")
            return

        messages = conversation.get_messages_for_api()

        # Call LLM with concurrent switching monitor
        try:
            response = await _call_with_monitor(
                messages=messages,
                tools=tool_definitions if tool_definitions else None,
                model=model,
            )
        except Exception as e:
            logger.error("LLM call failed: %s", e, exc_info=True)
            yield AgentStep(type="error", error=f"LLM error: {e}")
            return

        # Check cancellation after LLM call
        if cancel_event and cancel_event.is_set():
            yield AgentStep(type="cancelled", content="Agent stopped by user.")
            return

        # Yield any switching events that were collected
        for step in response["switching_steps"]:
            yield step

        result = response["result"]
        choice = result["choices"][0]
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
                # Check cancellation before each tool execution
                if cancel_event and cancel_event.is_set():
                    yield AgentStep(type="cancelled", content="Agent stopped by user.")
                    return

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
                yield AgentStep(
                    type="tool_call",
                    tool_call=tool_call,
                    iteration=iteration + 1,
                    max_iterations=max_iter,
                )

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
            f"Agent reached maximum iterations ({max_iter}). "
            "Stopping."
        ),
    )


async def _call_with_monitor(
    messages: list[dict],
    tools: list[dict] | None,
    model: str | None,
) -> dict[str, Any]:
    """
    Call chat_completion() and concurrently monitor model-router switching status.

    Returns dict with:
      - "result": the chat completion response
      - "switching_steps": list of AgentStep events collected during switching
    """
    switching_steps: list[AgentStep] = []

    async def monitor():
        """Poll model-router /v1/status every 2s, collect switching events."""
        await asyncio.sleep(1)  # Wait a bit before first check
        while True:
            try:
                status = await get_router_status()
                if status.get("is_switching"):
                    phase = status.get("phase", "unknown")
                    elapsed = status.get("elapsed")
                    message = _PHASE_MESSAGES.get(phase, phase)

                    if elapsed and elapsed > 300:
                        message = f"⚠ タイムアウト警告: {message}（{elapsed}秒経過）"

                    switching_steps.append(AgentStep(
                        type="switching",
                        switching=SwitchingInfo(
                            phase=phase,
                            elapsed=elapsed,
                            message=message,
                        ),
                    ))

                # Check for service errors only during model switching
                if status.get("is_switching"):
                    services = status.get("services", {})
                    for name, svc in services.items():
                        if svc.get("status") == "error":
                            switching_steps.append(AgentStep(
                                type="switching",
                                switching=SwitchingInfo(
                                    phase="error",
                                    elapsed=status.get("elapsed"),
                                    message=f"サービスエラー: {name} - {svc.get('message', '')}",
                                ),
                            ))
            except Exception as e:
                switching_steps.append(AgentStep(
                    type="switching",
                    switching=SwitchingInfo(
                        phase="error",
                        elapsed=None,
                        message=f"model-router 接続エラー: {e}",
                    ),
                ))
                # Don't spam on connection errors - wait longer
                await asyncio.sleep(5)
                continue

            await asyncio.sleep(2)

    monitor_task = asyncio.create_task(monitor())
    try:
        result = await chat_completion(
            messages=messages,
            tools=tools,
            model=model,
        )
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    return {"result": result, "switching_steps": switching_steps}
