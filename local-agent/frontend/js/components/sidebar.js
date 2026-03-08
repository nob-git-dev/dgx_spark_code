/**
 * Sidebar — conversation list management
 */
import { api } from "../api-client.js";
import { store } from "../store/state.js";

const listEl = document.getElementById("conversation-list");

/**
 * Render the conversation list
 */
export function renderSidebar() {
  if (!listEl) return;

  if (store.conversations.length === 0) {
    listEl.innerHTML = `
      <div style="padding: 16px; text-align: center; color: var(--text-tertiary); font-size: 13px;">
        No conversations yet
      </div>
    `;
    return;
  }

  listEl.innerHTML = store.conversations
    .map((c) => {
      const isActive = c.id === store.currentConversationId;
      const title = c.title || "New Chat";
      return `
        <div class="conversation-item ${isActive ? "active" : ""}"
             data-id="${c.id}">
          <span class="conv-title">${escapeHtml(title)}</span>
          <button class="delete-btn" data-delete-id="${c.id}" title="Delete">✕</button>
        </div>
      `;
    })
    .join("");

  // Bind click events
  listEl.querySelectorAll(".conversation-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      // Don't switch if clicking delete
      if (e.target.classList.contains("delete-btn")) return;
      const id = el.dataset.id;
      store.setCurrentConversation(id);
      renderSidebar();
    });
  });

  listEl.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.deleteId;
      await api.deleteConversation(id);
      store.setConversations(
        store.conversations.filter((c) => c.id !== id)
      );
      if (store.currentConversationId === id) {
        store.setCurrentConversation(null);
      }
    });
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Re-render on conversation changes
store.on("conversations-changed", renderSidebar);
