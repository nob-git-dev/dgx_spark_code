/**
 * Message rendering components
 */

const TOOL_ICONS = {
  web_search: "🔍",
  read_file: "📄",
  write_file: "✏️",
  list_files: "📁",
  execute_command: "💻",
  search_documents: "📚",
};

/**
 * Render markdown text to HTML using marked.js
 */
function renderMarkdown(text) {
  if (typeof marked !== "undefined" && marked.parse) {
    return marked.parse(text);
  }
  // Fallback: basic escaping
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

/**
 * Create a user message element
 */
export function createUserMessage(content) {
  const div = document.createElement("div");
  div.className = "message message-user";
  div.innerHTML = `<div class="message-bubble">${escapeHtml(content)}</div>`;
  return div;
}

/**
 * Create an assistant message container (filled incrementally via SSE)
 */
export function createAssistantMessage() {
  const div = document.createElement("div");
  div.className = "message message-assistant";

  const contentDiv = document.createElement("div");
  contentDiv.className = "message-content";
  div.appendChild(contentDiv);

  // Add loading indicator
  const loading = document.createElement("div");
  loading.className = "loading-dots";
  loading.innerHTML = "<span></span><span></span><span></span>";
  contentDiv.appendChild(loading);

  return div;
}

/**
 * Add thinking/reasoning block to assistant message
 */
export function appendThinking(messageEl, reasoning) {
  removeLoading(messageEl);
  const content = messageEl.querySelector(".message-content");

  const block = document.createElement("div");
  block.className = "thinking-block";
  block.innerHTML = `
    <div class="thinking-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
      💭 Thinking...
    </div>
    <div class="thinking-content collapsed">${escapeHtml(reasoning)}</div>
  `;
  content.appendChild(block);
}

/**
 * Add tool call step to assistant message
 */
export function appendToolCall(messageEl, toolCall) {
  removeLoading(messageEl);
  const content = messageEl.querySelector(".message-content");

  const icon = TOOL_ICONS[toolCall.name] || "🔧";
  const argsPreview = JSON.stringify(toolCall.arguments).slice(0, 80);

  const step = document.createElement("div");
  step.className = "tool-step";
  step.dataset.toolCallId = toolCall.id;
  step.innerHTML = `
    <div class="tool-step-header" onclick="this.parentElement.classList.toggle('expanded')">
      <span class="tool-icon">${icon}</span>
      <span class="tool-name">${escapeHtml(toolCall.name)}</span>
      <span class="tool-args-preview">${escapeHtml(argsPreview)}</span>
      <span class="tool-step-toggle">▼</span>
    </div>
    <div class="tool-step-body">
      <div class="tool-section-label">Arguments</div>
      <div class="tool-section-content">${escapeHtml(JSON.stringify(toolCall.arguments, null, 2))}</div>
      <div class="tool-section-label">Result</div>
      <div class="tool-section-content tool-result-content">
        <span class="pulse">executing...</span>
      </div>
    </div>
  `;
  content.appendChild(step);
}

/**
 * Update tool result in the matching tool step
 */
export function updateToolResult(messageEl, toolResult) {
  const step = messageEl.querySelector(
    `.tool-step[data-tool-call-id="${toolResult.tool_call_id}"]`
  );
  if (step) {
    const resultEl = step.querySelector(".tool-result-content");
    if (resultEl) {
      resultEl.textContent = toolResult.content;
    }
  }
}

/**
 * Add final answer to assistant message
 */
export function appendAnswer(messageEl, content) {
  removeLoading(messageEl);
  const contentDiv = messageEl.querySelector(".message-content");

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.innerHTML = renderMarkdown(content);
  contentDiv.appendChild(bubble);
}

/**
 * Add error block to assistant message
 */
export function appendError(messageEl, error) {
  removeLoading(messageEl);
  const content = messageEl.querySelector(".message-content");

  const block = document.createElement("div");
  block.className = "error-block";
  block.textContent = error;
  content.appendChild(block);
}

/**
 * Remove loading dots
 */
function removeLoading(messageEl) {
  const loading = messageEl.querySelector(".loading-dots");
  if (loading) loading.remove();
}

/**
 * Escape HTML characters
 */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
