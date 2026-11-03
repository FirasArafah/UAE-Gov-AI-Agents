import { api } from "../js/api.js";
import { agentColor, agentInitials, agentName } from "../js/agents.js";
import { h, renderMessage } from "../js/render.js";
import { streamPost } from "../js/sse.js";

const SUGGESTIONS = [
  { text: "Does UAE PDPL Article (18) give visa applicants a right to object to automated decisions?", agents: ["privacy"] },
  { text: "Which authority can order a government AI screening system to be paused, and on what legal basis?", agents: ["icp", "auditor", "privacy"] },
  { text: "What do international references require for human oversight of high-risk AI used in public services?", agents: ["auditor"] },
  { text: "هل تنطبق أحكام قانون حماية البيانات الشخصية على الجهات الحكومية؟", agents: ["privacy", "icp"] },
];

let sessionId = null;

export async function renderChat(container) {
  const log = h("div", { class: "chat-log", "aria-live": "polite" });
  const picker = h("div", { class: "agent-picker", role: "group", "aria-label": "Agents to ask" }, h("small", { class: "muted", text: "Ask:" }));
  const input = h("textarea", { class: "input", rows: 1, dir: "auto", placeholder: "Ask about a law, a mandate or an incident…", "aria-label": "Message" });
  const send = h("button", { class: "btn primary", type: "submit", text: "Send" });
  const hint = h("small", { class: "muted" });
  const status = h("p", { class: "error", role: "alert" });
  const suggestions = h("div", { class: "suggestions" });
  const form = h("form", { class: "composer" }, picker, h("div", { class: "composer-row" }, input, send), hint);

  container.append(
    h("div", { class: "chat-layout" },
      h("div", { class: "page-head" },
        h("div", {},
          h("div", { class: "eyebrow", text: "Ask agents" }),
          h("h1", { text: "Question the agents directly" }),
          h("p", { text: "Every answer is grounded in retrieved excerpts and checked for citation errors. Select several agents to get independent answers plus a Coordinator synthesis." }),
        ),
        h("button", { class: "btn ghost", type: "button", text: "New conversation", onclick: () => { sessionId = null; log.innerHTML = ""; showSuggestions(); } }),
      ),
      suggestions,
      log,
      status,
      form,
    ),
  );

  const selected = new Set(["auditor"]);
  let agents = [];
  try {
    agents = await api("/agents");
  } catch (err) {
    status.textContent = "Could not load agents: " + err.message;
  }

  function drawPicker() {
    picker.querySelectorAll(".agent-toggle").forEach((b) => b.remove());
    for (const a of agents) {
      picker.append(
        h("button", {
          class: "agent-toggle", type: "button", "--agent": agentColor(a.slug),
          "aria-pressed": String(selected.has(a.slug)),
          onclick: () => {
            if (selected.has(a.slug) && selected.size > 1) selected.delete(a.slug);
            else selected.add(a.slug);
            drawPicker();
          },
        }, h("i"), a.name),
      );
    }
    const many = [...selected].filter((s) => s !== "coordinator").length > 1 && !selected.has("coordinator");
    hint.textContent = many
      ? "Each selected agent answers independently, then the Coordinator synthesizes their answers."
      : "Enter to send · Shift+Enter for a new line";
  }
  drawPicker();

  function showSuggestions() {
    suggestions.innerHTML = "";
    if (log.childElementCount) return;
    for (const s of SUGGESTIONS) {
      suggestions.append(
        h("button", {
          class: "suggestion", type: "button", dir: "auto", text: s.text,
          onclick: () => {
            selected.clear();
            s.agents.forEach((a) => selected.add(a));
            drawPicker();
            input.value = s.text;
            input.focus();
            autosize();
          },
        }),
      );
    }
  }
  showSuggestions();

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  function startBubble(data) {
    const slug = data.agent_slug;
    const content = h("div", { class: "prose streaming", dir: "auto" });
    const thinking = h("pre", { class: "trace", hidden: true });
    const el = h("article", { class: "msg" + (data.is_synthesis ? " synthesis" : ""), "--agent": agentColor(slug) },
      data.is_synthesis ? h("div", { class: "synth-banner", text: "Coordinator synthesis" }) : null,
      h("div", { class: "msg-head" },
        h("span", { class: "avatar", text: agentInitials(slug, data.agent_name) }),
        h("div", { class: "who" }, h("b", { text: agentName(slug, data.agent_name) }), h("small", { text: "retrieving sources and drafting…" })),
        h("span", { class: "pulse" }),
      ),
      h("div", { class: "msg-body" }, thinking, content),
    );
    log.append(el);
    return { el, content, thinking, data, thinkingText: "", contentText: "" };
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;

    input.disabled = send.disabled = true;
    status.textContent = "";
    suggestions.innerHTML = "";
    log.append(h("div", { class: "bubble-user", dir: "auto", text }));
    input.value = "";
    autosize();

    let current = null;
    try {
      if (!sessionId) {
        const s = await api("/sessions", { method: "POST", body: JSON.stringify({}) });
        sessionId = s.id;
      }
      await streamPost(`/sessions/${sessionId}/stream`, { message: text, agents: [...selected] }, (event, data) => {
        if (event === "agent_start") {
          current = startBubble(data);
        } else if (event === "thinking_chunk" && current) {
          current.thinkingText += data.content;
          current.thinking.hidden = false;
          current.thinking.textContent = current.thinkingText;
          current.thinking.scrollTop = current.thinking.scrollHeight;
        } else if (event === "content_chunk" && current) {
          current.contentText += data.content;
          current.thinking.hidden = true;
          current.content.textContent = current.contentText;
        } else if (event === "agent_done" && current) {
          // Re-render the finished answer with language tabs, citations and sources.
          const finished = renderMessage({
            agent_slug: current.data.agent_slug,
            agent_name: current.data.agent_name,
            // The server's final text has reasoning that escaped its tags moved out.
            content: data.content || current.contentText,
            thinking: data.thinking || current.thinkingText,
            references: data.references,
            is_synthesis: data.is_synthesis,
            responding_to: current.data.responding_to,
          });
          current.el.replaceWith(finished);
          current = null;
        } else if (event === "error") {
          status.textContent = `${agentName(data.agent_slug)}: ${data.message}`;
        }
        if (current) current.el.scrollIntoView({ block: "end" });
      });
    } catch (err) {
      status.textContent = "Chat failed: " + err.message;
    }

    input.disabled = send.disabled = false;
    input.focus();
  });
}
