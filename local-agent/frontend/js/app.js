/**
 * Local Agent — Main application entry
 */
import { api, sendMessage } from "./api-client.js";
import { store } from "./store/state.js";
import {
  createUserMessage,
  createAssistantMessage,
  appendThinking,
  appendToolCall,
  updateToolResult,
  appendAnswer,
  appendError,
} from "./components/message.js";
import { renderSidebar } from "./components/sidebar.js";
import { initInput, consumeInput, setInputEnabled } from "./components/chat-input.js";

// DOM references
const messagesEl = document.getElementById("messages");
const chatContainer = document.getElementById("chat-container");
const chatTitle = document.getElementById("chat-title");
const fileInput = document.getElementById("file-input");
const uploadStatus = document.getElementById("upload-status");
const sidebarToggle = document.getElementById("btn-sidebar-toggle");
const sidebar = document.getElementById("sidebar");
const newChatBtn = document.getElementById("btn-new-chat");
const sendBtn = document.getElementById("btn-send");
const chatInput = document.getElementById("chat-input");

/**
 * Initialize the application
 */
async function init() {
  initInput();

  // Load conversations
  try {
    const conversations = await api.getConversations();
    store.setConversations(conversations);
  } catch {
    // Backend might not be ready yet
    console.warn("Could not load conversations");
  }

  renderSidebar();
  bindEvents();
}

/**
 * Bind all UI event handlers
 */
function bindEvents() {
  // Send message
  sendBtn.addEventListener("click", handleSend);
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  // New chat
  newChatBtn.addEventListener("click", startNewChat);

  // File upload
  fileInput.addEventListener("change", handleUpload);

  // Sidebar toggle
  sidebarToggle.addEventListener("click", () => {
    sidebar.classList.toggle("hidden");
  });

  // Conversation selection
  store.on("conversation-selected", (id) => {
    const conv = store.conversations.find((c) => c.id === id);
    if (conv) {
      chatTitle.textContent = conv.title || "New Chat";
    }
  });
}

/**
 * Handle sending a message
 */
async function handleSend() {
  const message = consumeInput();
  if (!message || store.isStreaming) return;

  // Clear welcome message on first send
  const welcome = messagesEl.querySelector(".welcome-message");
  if (welcome) welcome.remove();

  store.setStreaming(true);
  setInputEnabled(false);

  // Add user message
  messagesEl.appendChild(createUserMessage(message));

  // Create assistant message container
  const assistantEl = createAssistantMessage();
  messagesEl.appendChild(assistantEl);
  scrollToBottom();

  try {
    await sendMessage(
      message,
      store.currentConversationId,
      (step) => {
        switch (step.type) {
          case "conversation_id":
            store.setCurrentConversation(step.conversation_id);
            // Add to sidebar if new
            if (!store.conversations.find((c) => c.id === step.conversation_id)) {
              store.conversations.unshift({
                id: step.conversation_id,
                title: message.slice(0, 50),
                created_at: new Date().toISOString(),
              });
              store.setConversations([...store.conversations]);
            }
            break;

          case "thinking":
            appendThinking(assistantEl, step.reasoning);
            break;

          case "tool_call":
            appendToolCall(assistantEl, step.tool_call);
            break;

          case "tool_result":
            updateToolResult(assistantEl, step.tool_result);
            break;

          case "answer":
            appendAnswer(assistantEl, step.content);
            break;

          case "error":
            appendError(assistantEl, step.error);
            break;

          case "done":
            break;
        }
        scrollToBottom();
      }
    );
  } catch (err) {
    appendError(assistantEl, `Connection error: ${err.message}`);
  }

  store.setStreaming(false);
  setInputEnabled(true);

  // Refresh sidebar
  try {
    const conversations = await api.getConversations();
    store.setConversations(conversations);
  } catch {
    // Ignore
  }
}

/**
 * Start a new chat
 */
function startNewChat() {
  store.setCurrentConversation(null);
  chatTitle.textContent = "New Chat";
  messagesEl.innerHTML = `
    <div class="welcome-message">
      <h3>Local Agent</h3>
      <p>GPT-OSS-120B-128K で動作するローカルAIエージェントです。</p>
      <div class="capabilities">
        <div class="capability">🔍 Web検索</div>
        <div class="capability">📁 ファイル操作</div>
        <div class="capability">💻 コマンド実行</div>
        <div class="capability">📄 文書検索 (RAG)</div>
      </div>
    </div>
  `;
  renderSidebar();
}

/**
 * Handle file upload for RAG
 */
async function handleUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  uploadStatus.textContent = `Uploading ${file.name}...`;

  try {
    const result = await api.uploadDocument(file);
    uploadStatus.textContent = `✅ ${result.filename} (${result.chunks} chunks indexed)`;
    setTimeout(() => {
      uploadStatus.textContent = "";
    }, 5000);
  } catch (err) {
    uploadStatus.textContent = `❌ Upload failed: ${err.message}`;
  }

  // Reset file input
  fileInput.value = "";
}

/**
 * Scroll chat to bottom
 */
function scrollToBottom() {
  requestAnimationFrame(() => {
    chatContainer.scrollTop = chatContainer.scrollHeight;
  });
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", init);
