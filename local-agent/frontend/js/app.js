/**
 * Local Agent — Main application entry
 */
import { api, sendMessage, cancelChat } from "./api-client.js";
import { store } from "./store/state.js";
import {
  createUserMessage,
  createAssistantMessage,
  appendThinking,
  appendToolCall,
  updateToolResult,
  appendAnswer,
  appendError,
  appendSwitching,
} from "./components/message.js";
import { renderSidebar } from "./components/sidebar.js";
import { initInput, consumeInput, setInputEnabled, isComposing } from "./components/chat-input.js";

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
const stopBtn = document.getElementById("btn-stop");
const chatInput = document.getElementById("chat-input");
const modelSelect = document.getElementById("model-select");

/**
 * Initialize the application
 */
async function init() {
  initInput();

  // Load conversations and models in parallel
  const [convResult, modelsResult] = await Promise.allSettled([
    api.getConversations(),
    api.getModels(),
  ]);

  if (convResult.status === "fulfilled") {
    store.setConversations(convResult.value);
  } else {
    console.warn("Could not load conversations");
  }

  if (modelsResult.status === "fulfilled") {
    populateModelSelect(modelsResult.value.models || []);
  } else {
    console.warn("Could not load models");
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
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.isComposing && !isComposing()) {
      e.preventDefault();
      handleSend();
    }
  });

  // Stop generating
  stopBtn.addEventListener("click", handleStop);

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
 * Populate model selector with available models
 */
function populateModelSelect(models) {
  modelSelect.innerHTML = "";
  const defaultModel = "gpt-oss-120b-128k";
  let hasDefault = false;

  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = m.id;
    if (m.id === defaultModel) {
      opt.selected = true;
      hasDefault = true;
    }
    modelSelect.appendChild(opt);
  }

  if (!hasDefault && models.length > 0) {
    modelSelect.value = models[0].id;
  }
}

/**
 * Show/hide send vs stop button based on streaming state
 */
function updateButtonState(streaming) {
  if (streaming) {
    sendBtn.style.display = "none";
    stopBtn.style.display = "";
  } else {
    sendBtn.style.display = "";
    stopBtn.style.display = "none";
  }
}

/**
 * Handle stopping generation
 */
function handleStop() {
  if (!store.isStreaming || !store.abortController) return;
  store.abortController.abort();
  // Also tell the backend to cancel
  if (store.currentConversationId) {
    cancelChat(store.currentConversationId);
  }
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

  // Set up abort controller
  const abortController = new AbortController();
  store.abortController = abortController;

  store.setStreaming(true);
  setInputEnabled(false);
  updateButtonState(true);

  // Add user message
  messagesEl.appendChild(createUserMessage(message));

  // Create assistant message container
  const assistantEl = createAssistantMessage();
  messagesEl.appendChild(assistantEl);
  scrollToBottom();

  try {
    const selectedModel = modelSelect.value;
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
            // Update iteration counter if available
            if (step.iteration != null) {
              updateIterationCounter(assistantEl, step.iteration, step.max_iterations);
            }
            break;

          case "tool_result":
            updateToolResult(assistantEl, step.tool_result);
            break;

          case "answer":
            appendAnswer(assistantEl, step.content);
            removeIterationCounter(assistantEl);
            break;

          case "switching":
            appendSwitching(assistantEl, step.switching);
            break;

          case "cancelled":
            appendError(assistantEl, step.content || "Stopped by user.");
            removeIterationCounter(assistantEl);
            break;

          case "error":
            appendError(assistantEl, step.error);
            removeIterationCounter(assistantEl);
            break;

          case "done":
            removeIterationCounter(assistantEl);
            break;
        }
        scrollToBottom();
      },
      selectedModel,
      abortController.signal,
    );
  } catch (err) {
    if (err.name !== "AbortError") {
      appendError(assistantEl, `Connection error: ${err.message}`);
    }
  }

  store.abortController = null;
  store.setStreaming(false);
  setInputEnabled(true);
  updateButtonState(false);

  // Remove loading dots if still present
  const loading = assistantEl.querySelector(".loading-dots");
  if (loading) loading.remove();

  // Refresh sidebar
  try {
    const conversations = await api.getConversations();
    store.setConversations(conversations);
  } catch {
    // Ignore
  }
}

/**
 * Update or create the iteration counter on an assistant message
 */
function updateIterationCounter(assistantEl, iteration, maxIterations) {
  let counter = assistantEl.querySelector(".iteration-counter");
  if (!counter) {
    counter = document.createElement("div");
    counter.className = "iteration-counter";
    const content = assistantEl.querySelector(".message-content");
    if (content) content.appendChild(counter);
  }
  counter.textContent = `Step ${iteration}/${maxIterations}`;
}

/**
 * Remove the iteration counter
 */
function removeIterationCounter(assistantEl) {
  const counter = assistantEl.querySelector(".iteration-counter");
  if (counter) counter.remove();
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
      <p>ローカルAIエージェント — モデルを選択して対話できます。</p>
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
