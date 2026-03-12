/**
 * API client for Local Agent backend
 */

async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export const api = {
  getConversations() {
    return apiFetch("/api/v1/conversations");
  },

  getModels() {
    return apiFetch("/api/v1/models");
  },

  deleteConversation(id) {
    return apiFetch(`/api/v1/conversations/${id}`, { method: "DELETE" });
  },

  async uploadDocument(file) {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/v1/upload", {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(`Upload failed: HTTP ${res.status}`);
    return res.json();
  },
};

/**
 * Cancel an active agent run for a conversation.
 */
export async function cancelChat(conversationId) {
  try {
    await apiFetch(`/api/v1/chat/${conversationId}/cancel`, { method: "POST" });
  } catch {
    // Ignore errors (e.g., already finished)
  }
}

/**
 * Send a chat message via POST and parse SSE stream.
 * EventSource only supports GET, so we use fetch + ReadableStream.
 * Accepts an optional AbortSignal for cancellation.
 */
export async function sendMessage(message, conversationId, onStep, model = null, signal = null) {
  const body = { message, conversation_id: conversationId };
  if (model) body.model = model;

  const fetchOptions = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  if (signal) fetchOptions.signal = signal;

  const res = await fetch("/api/v1/chat", fetchOptions);

  if (!res.ok) {
    throw new Error(`Chat failed: HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // Keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.slice(6));
            onStep(data);
          } catch {
            // Skip malformed data
          }
        }
      }
    }

    // Process remaining buffer
    if (buffer.startsWith("data: ")) {
      try {
        const data = JSON.parse(buffer.slice(6));
        onStep(data);
      } catch {
        // Skip
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      // Stream was aborted by user — not an error
      return;
    }
    throw err;
  }
}
