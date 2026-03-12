"""Agent data models"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """A single tool call from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """Result of executing a tool."""
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


class SwitchingInfo(BaseModel):
    """Model switching progress info from model-router."""
    phase: str
    elapsed: int | None = None
    message: str


class AgentStep(BaseModel):
    """A single step in the ReAct loop, emitted via SSE."""
    type: str  # "thinking", "tool_call", "tool_result", "answer", "error", "switching", "cancelled"
    reasoning: str | None = None
    tool_call: ToolCall | None = None
    tool_result: ToolResult | None = None
    content: str | None = None
    error: str | None = None
    switching: SwitchingInfo | None = None
    iteration: int | None = None
    max_iterations: int | None = None


class ConversationTurn(BaseModel):
    """One user message + agent response (all steps)."""
    user_message: str
    steps: list[AgentStep] = Field(default_factory=list)
    final_answer: str | None = None
