/**
 * Chat input — auto-resize textarea
 */

const input = document.getElementById("chat-input");
const sendBtn = document.getElementById("btn-send");

/**
 * Initialize input behaviors
 */
export function initInput() {
  if (!input || !sendBtn) return;

  // Auto-resize textarea
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 150) + "px";

    // Enable/disable send button
    sendBtn.disabled = !input.value.trim();
  });

  // Initial state
  sendBtn.disabled = true;
}

/**
 * Get and clear the input value
 */
export function consumeInput() {
  const value = input.value.trim();
  input.value = "";
  input.style.height = "auto";
  sendBtn.disabled = true;
  return value;
}

/**
 * Set input enabled/disabled state
 */
export function setInputEnabled(enabled) {
  input.disabled = !enabled;
  sendBtn.disabled = !enabled;
  if (enabled) {
    input.focus();
  }
}
