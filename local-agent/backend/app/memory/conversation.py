"""Conversation history management (in-memory)"""

import uuid
from datetime import datetime


class Conversation:
    """A single conversation with message history."""

    def __init__(self, conversation_id: str | None = None):
        self.id = conversation_id or str(uuid.uuid4())
        self.created_at = datetime.now()
        self.title: str | None = None
        self._messages: list[dict] = []

    def get_system_prompt(self) -> str:
        return (
            "You are a helpful AI assistant running locally. "
            "You have access to tools for web search, file operations, "
            "command execution, and document search. "
            "Use tools when needed to answer questions accurately. "
            "When you use a tool, explain what you are doing and why. "
            "If a task requires multiple steps, plan them out first. "
            "Always respond in the same language as the user's message."
        )

    def get_messages_for_api(self) -> list[dict]:
        """Return conversation history in OpenAI message format."""
        messages = [{"role": "system", "content": self.get_system_prompt()}]
        messages.extend(self._messages)
        return messages

    def add_user_message(self, content: str):
        self._messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str):
        self._messages.append({"role": "assistant", "content": content})

    def add_tool_call_message(
        self,
        content: str | None,
        tool_calls: list[dict],
    ):
        self._messages.append({
            "role": "assistant",
            "content": content or "",
            "tool_calls": tool_calls,
        })

    def add_tool_result_message(
        self,
        tool_call_id: str,
        name: str,
        content: str,
    ):
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })

    def auto_title(self, user_message: str):
        """Set title from first user message if not set."""
        if self.title is None:
            self.title = (
                user_message[:50] + "..."
                if len(user_message) > 50
                else user_message
            )


class ConversationStore:
    """In-memory store for all conversations."""

    def __init__(self):
        self._conversations: dict[str, Conversation] = {}

    def create(self) -> Conversation:
        conv = Conversation()
        self._conversations[conv.id] = conv
        return conv

    def get(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    def list_all(self) -> list[dict]:
        return [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat(),
            }
            for c in sorted(
                self._conversations.values(),
                key=lambda c: c.created_at,
                reverse=True,
            )
        ]

    def delete(self, conversation_id: str):
        self._conversations.pop(conversation_id, None)
