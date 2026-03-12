/**
 * Observable state store (launcher pattern)
 */
export const store = {
  conversations: [],
  currentConversationId: null,
  isStreaming: false,
  abortController: null,

  _listeners: {},

  on(event, fn) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(fn);
  },

  off(event, fn) {
    if (!this._listeners[event]) return;
    this._listeners[event] = this._listeners[event].filter(f => f !== fn);
  },

  emit(event, data) {
    (this._listeners[event] || []).forEach(fn => fn(data));
  },

  setConversations(list) {
    this.conversations = list;
    this.emit("conversations-changed", list);
  },

  setCurrentConversation(id) {
    this.currentConversationId = id;
    this.emit("conversation-selected", id);
  },

  setStreaming(val) {
    this.isStreaming = val;
    this.emit("streaming-changed", val);
  },
};
