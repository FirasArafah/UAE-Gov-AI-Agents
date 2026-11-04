import { streamPost } from "./sse.js";

/**
 * One chat's two-way channel to the backend. ask() streams an answer's events and resolves when
 * it is done; stop() cuts the current answer short. If the WebSocket cannot be opened, ask()
 * falls back to the one-way SSE endpoint, where stop() only stops listening.
 */
export class ChatSocket {
  constructor(sessionId) {
    this.sessionId = sessionId;
    this.ws = null;
    this.current = null; // { onEvent, resolve, reject }
    this.fallbackAbort = null;
  }

  async #open() {
    if (this.ws?.readyState === WebSocket.OPEN) return this.ws;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/api/ws/sessions/${this.sessionId}/chat`);
    await new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", () => reject(new Error("socket unavailable")), { once: true });
    });
    ws.addEventListener("message", (msg) => {
      const { event, data } = JSON.parse(msg.data);
      if (!this.current) return;
      this.current.onEvent(event, data);
      if (event === "done") {
        this.current.resolve(data);
        this.current = null;
      }
    });
    ws.addEventListener("close", () => {
      this.current?.reject(new Error("connection closed"));
      this.current = null;
      this.ws = null;
    });
    this.ws = ws;
    return ws;
  }

  async ask(message, agents, onEvent) {
    let ws;
    try {
      ws = await this.#open();
    } catch {
      const controller = new AbortController();
      this.fallbackAbort = controller;
      try {
        await streamPost(`/sessions/${this.sessionId}/stream`, { message, agents }, onEvent, controller.signal);
      } finally {
        this.fallbackAbort = null;
      }
      return {};
    }
    return new Promise((resolve, reject) => {
      this.current = { onEvent, resolve, reject };
      ws.send(JSON.stringify({ type: "ask", message, agents }));
    });
  }

  stop() {
    if (this.ws?.readyState === WebSocket.OPEN && this.current) {
      this.ws.send(JSON.stringify({ type: "stop" }));
    }
    this.fallbackAbort?.abort();
  }

  close() {
    this.ws?.close();
    this.ws = null;
  }
}
