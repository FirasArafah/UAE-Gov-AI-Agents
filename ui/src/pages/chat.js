import { api } from "../js/api.js";
import { agentColor } from "../js/agents.js";
import { streamPost } from "../js/sse.js";

let sessionId = null;

export async function renderChat(container) {
  container.innerHTML = `
    <h1>Free Chat</h1>
    <div id="log" class="chat"></div>
    <form id="form" class="chat-form">
      <select id="agent"></select>
      <input id="msg" type="text" dir="auto" autocomplete="off"
             placeholder="Ask an agent..." required />
      <button id="send" class="btn primary" type="submit">Send</button>
    </form>
    <p id="status" class="error"></p>`;

  const log = container.querySelector("#log");
  const form = container.querySelector("#form");
  const select = container.querySelector("#agent");
  const input = container.querySelector("#msg");
  const send = container.querySelector("#send");
  const status = container.querySelector("#status");

  try {
    const agents = await api("/agents");
    for (const a of agents) {
      const opt = document.createElement("option");
      opt.value = a.slug;
      opt.textContent = a.name;
      select.appendChild(opt);
    }
    select.value = "auditor";
  } catch (err) {
    status.textContent = "Could not load agents: " + err.message;
  }

  function addUser(text) {
    const b = document.createElement("article");
    b.className = "bubble user";
    b.style.setProperty("--agent", "#6b7280");
    b.innerHTML = "<b>You</b><p dir='auto'></p>";
    b.querySelector("p").textContent = text;
    log.appendChild(b);
  }

  function addAgent(slug, name) {
    const b = document.createElement("article");
    b.className = "bubble";
    b.style.setProperty("--agent", agentColor(slug));
    b.innerHTML = `
      <b></b>
      <pre class="thinking-box" hidden></pre>
      <p class="content" dir="auto"></p>
      <button class="btn toggle" type="button" hidden>Show thinking</button>`;
    b.querySelector("b").textContent = name || slug;
    const thinking = b.querySelector(".thinking-box");
    const toggle = b.querySelector(".toggle");
    toggle.addEventListener("click", () => {
      thinking.hidden = !thinking.hidden;
      toggle.textContent = thinking.hidden ? "Show thinking" : "Hide thinking";
    });
    log.appendChild(b);
    return {
      bubble: b,
      thinking,
      toggle,
      content: b.querySelector(".content"),
    };
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    input.disabled = send.disabled = select.disabled = true;
    status.textContent = "";
    addUser(text);
    input.value = "";

    let current = null;
    try {
      if (!sessionId) {
        const s = await api("/sessions", { method: "POST", body: JSON.stringify({}) });
        sessionId = s.id;
      }

      await streamPost(
        `/sessions/${sessionId}/stream`,
        { message: text, agents: [select.value] },
        (event, data) => {
          if (event === "agent_start") {
            current = addAgent(data.agent_slug, data.agent_name);
          } else if (event === "thinking_chunk" && current) {
            current.thinking.hidden = false;
            current.thinking.textContent += data.content;
            current.thinking.scrollTop = current.thinking.scrollHeight;
          } else if (event === "content_chunk" && current) {
            current.content.textContent += data.content;
          } else if (event === "agent_done" && current) {
            if (current.thinking.textContent) {
              current.thinking.hidden = true;
              current.toggle.hidden = false;
            }
          } else if (event === "error") {
            status.textContent = "Agent error: " + data.message;
          }
          window.scrollTo(0, document.body.scrollHeight);
        }
      );
    } catch (err) {
      status.textContent = "Chat failed: " + err.message;
    }

    input.disabled = send.disabled = select.disabled = false;
    input.focus();
  });
}