import { api } from "../js/api.js";
import { AGENTS, agentColor, agentName } from "../js/agents.js";
import { h, renderAnswer } from "../js/render.js";
import { streamPost } from "../js/sse.js";

const TEAM = ["icp", "auditor", "privacy", "coordinator"];

const SUGGESTIONS = [
  "Which authority can order a government AI screening system to be paused, and on what legal basis?",
  "Does UAE PDPL Article (18) give visa applicants a right to object to automated decisions?",
  "What do international references require for human oversight of high-risk AI in public services?",
  "هل تنطبق أحكام قانون حماية البيانات الشخصية على الجهات الحكومية؟",
];

const SESSION_KEY = "chatSession";

function storedSession() {
  try {
    return sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function storeSession(id) {
  try {
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable */
  }
}

export function forgetChat() {
  storeSession(null);
}

function duration(ms) {
  const s = Math.max(1, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

const logo = () => [
  h("img", { class: "logo logo-on-light", src: "/logo-black.svg", alt: "", width: 28, height: 28 }),
  h("img", { class: "logo logo-on-dark", src: "/logo-white.svg", alt: "", width: 28, height: 28 }),
];

/**
 * One assistant turn. Specialists' reasoning and assessments go into a collapsible
 * "Thinking" panel; the final answer (Coordinator synthesis in team mode) is shown below it.
 */
function createTurn({ team, agents }) {
  const started = Date.now();
  const statusText = h("span", { text: team ? "The team is thinking" : "Thinking" });
  const timer = h("span", { class: "think-time", text: "" });
  const steps = h("div", { class: "think-body" });
  const think = h("details", { class: "think", open: true },
    h("summary", {}, h("span", { class: "think-spinner", "aria-hidden": "true" }), statusText, timer),
    steps,
  );
  const answer = h("div", { class: "answer-slot" });
  const names = agents.filter((s) => s !== "coordinator").map((s) => AGENTS[s]?.short || s).join(", ");
  const el = h("div", { class: "turn" },
    h("div", { class: "turn-avatar" }, logo()),
    h("div", { class: "turn-main" },
      h("div", { class: "turn-name" },
        h("b", { text: team ? "Mathuq team" : agentName(agents[0]) }),
        team ? h("small", { text: `${names} → Coordinator` }) : null,
      ),
      think,
      answer,
    ),
  );

  const tick = setInterval(() => {
    if (!el.isConnected) return clearInterval(tick);
    timer.textContent = duration(Date.now() - started);
  }, 1000);

  const bySlug = {};
  let finalText = "";
  let finalEl = null;
  const references = [];

  function step(slug, label) {
    const text = h("div", { class: "step-text", dir: "auto" });
    const out = h("div", { class: "step-out" });
    const meta = h("small", { text: label });
    const node = h("div", { class: "step", "--agent": agentColor(slug), "data-state": "active" },
      h("div", { class: "step-head" }, h("span", { class: "step-dot" }), h("b", { text: agentName(slug) }), meta),
      text,
      out,
    );
    steps.append(node);
    return (bySlug[slug] = { node, text, out, meta, content: "", thinking: "" });
  }

  return {
    el,
    start(data) {
      const isFinal = !team || data.is_synthesis;
      statusText.textContent = data.is_synthesis
        ? "Coordinator is writing the final answer"
        : `${agentName(data.agent_slug, data.agent_name)} is reasoning`;
      step(data.agent_slug, data.is_synthesis ? "reading the team's assessments" : "reasoning");
      if (isFinal) {
        finalEl = h("div", { class: "prose streaming", dir: "auto" });
        answer.replaceChildren(finalEl);
      }
    },
    thinking(data) {
      const s = bySlug[data.agent_slug];
      if (!s) return;
      s.thinking += data.content;
      s.text.textContent = s.thinking;
      s.text.scrollTop = s.text.scrollHeight;
    },
    content(data) {
      const s = bySlug[data.agent_slug];
      if (!s) return;
      s.content += data.content;
      const isFinal = !team || data.agent_slug === "coordinator";
      if (isFinal && finalEl) {
        finalText += data.content;
        finalEl.textContent = finalText;
      } else {
        s.meta.textContent = "drafting its assessment";
      }
    },
    done(data) {
      const s = bySlug[data.agent_slug];
      if (!s) return;
      s.node.dataset.state = "done";
      if (data.thinking) s.text.textContent = data.thinking;
      if (!s.text.textContent.trim()) s.text.replaceWith(h("div", { class: "step-empty", text: "The model returned no reasoning text for this step." }));
      const text = data.content || s.content;
      if (data.interrupted || /^\(stream interrupted/.test(text)) {
        s.node.dataset.state = "failed";
        s.meta.textContent = "could not answer — the model stopped before responding";
        if (!team || data.is_synthesis) answer.replaceChildren(h("div", { class: "notice danger", text: "The model stopped before answering. Please ask again." }));
        return;
      }
      const refs = data.references || [];
      const isFinal = !team || data.is_synthesis;
      if (isFinal) {
        s.meta.textContent = team ? "wrote the final answer" : `answered with ${refs.length} sources`;
        answer.replaceChildren(
          renderAnswer(text, team ? dedupe(references) : refs, {
            sourcesLabel: team ? "Sources consulted by the team" : "Sources",
          }),
        );
      } else {
        references.push(...refs);
        s.meta.textContent = `assessed with ${refs.length} sources`;
        s.out.append(
          h("details", { class: "step-answer" }, h("summary", { text: "Read assessment" }), renderAnswer(text, refs)),
        );
      }
    },
    error(message) {
      answer.append(h("div", { class: "notice danger", text: message }));
    },
    finish() {
      clearInterval(tick);
      const count = Object.keys(bySlug).length;
      statusText.textContent = `Chain of thought · ${duration(Date.now() - started)}`;
      timer.textContent = team ? `· ${count} agents` : "";
      think.classList.add("finished");
      if (!answer.childElementCount) answer.append(h("p", { class: "muted", text: "No answer was produced." }));
    },
  };
}

function dedupe(references) {
  const seen = new Set();
  return references.filter((r) => {
    const key = `${r.title}|${r.section}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Rebuild a finished turn from stored messages (after navigating away and back). */
function restoreTurn(assistantMsgs, agentsById) {
  const view = (m) => ({ slug: agentsById[m.agent_id]?.slug, meta: m.message_metadata || {}, m });
  const items = assistantMsgs.map(view);
  // The final answer is the Coordinator's synthesis, or the last answer in older chats.
  const final = items.find((i) => i.meta.is_synthesis) || items[items.length - 1];
  const team = items.length > 1;
  const turn = createTurn({ team, agents: items.map((i) => i.slug) });
  const ordered = [...items.filter((i) => i !== final), final];
  for (const i of ordered) {
    const isSynth = i === final;
    turn.start({ agent_slug: i.slug, is_synthesis: team && isSynth });
    turn.done({
      agent_slug: i.slug,
      content: i.m.content,
      thinking: i.m.thinking_trace,
      references: i.meta.references || [],
      is_synthesis: team && isSynth,
    });
  }
  turn.finish();
  turn.el.querySelector(".think summary span:nth-child(2)").textContent = "Chain of thought";
  return turn.el;
}

export async function renderChat(container, params = {}) {
  const thread = h("div", { class: "thread", "aria-live": "polite" });
  const empty = h("div", { class: "chat-empty" },
    h("h1", { text: "What should the agents look into?" }),
    h("p", { text: "Three specialist agents assess your question independently from retrieved law, then the Coordinator writes one answer. Each agent’s chain of thought stays visible." }),
    h("div", { class: "starter-grid" },
      SUGGESTIONS.map((text) => h("button", { class: "starter", type: "button", dir: "auto", text, onclick: () => { input.value = text; autosize(); input.focus(); } })),
    ),
  );
  const status = h("p", { class: "error", role: "alert" });
  const mode = h("select", { class: "mode-select", "aria-label": "Who answers" },
    h("option", { value: "team", text: "Team · all 4 agents" }),
    Object.entries(AGENTS).map(([slug, a]) => h("option", { value: slug, text: `${a.name} only` })),
  );
  const input = h("textarea", { class: "composer-input", rows: 1, dir: "auto", placeholder: "Message Mathuq…", "aria-label": "Message" });
  const send = h("button", { class: "send-btn", type: "submit", "aria-label": "Send", html: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 4l-7 7h4.5v9h5v-9H19z"/></svg>' });
  const note = h("small", { class: "composer-note", text: "Runs on a local LLM. A team answer takes several minutes on CPU." });
  const form = h("form", { class: "composer2" },
    h("div", { class: "chat-col" },
      h("div", { class: "composer-box" }, input, h("div", { class: "composer-row2" }, mode, h("span", { style: { flex: 1 } }), send)),
      note,
    ),
  );

  const scroller = h("div", { class: "chat-scroll" }, h("div", { class: "chat-col" }, empty, thread, status));
  const layout = h("div", { class: "chat2" }, scroller, form);
  container.append(layout);

  let sessionId = params.id || storedSession();
  if (params.id) storeSession(params.id);
  const agentsById = {};

  const setEmpty = (isEmpty) => {
    empty.hidden = !isEmpty;
    layout.classList.toggle("is-empty", isEmpty);
  };
  /** Follow new text only while the reader is at the bottom, so reading back is not interrupted. */
  const follow = (force = false) => {
    const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
    if (force || distance < 140) scroller.scrollTop = scroller.scrollHeight;
  };

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 200) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  try {
    for (const a of await api("/agents")) agentsById[a.id] = a;
  } catch (err) {
    status.textContent = "Could not load agents: " + err.message;
  }

  // Restore the conversation of this browser tab.
  if (sessionId) {
    try {
      const messages = await api(`/sessions/${sessionId}/messages`);
      let group = null;
      const flush = () => {
        if (group?.length) thread.append(restoreTurn(group, agentsById));
        group = null;
      };
      for (const m of messages) {
        if (m.role === "user") {
          flush();
          thread.append(h("div", { class: "user-msg", dir: "auto", text: m.content }));
          group = [];
        } else if (m.role === "assistant" && group) {
          group.push(m);
        }
      }
      flush();
    } catch {
      sessionId = null;
      storeSession(null);
    }
  }
  setEmpty(thread.childElementCount === 0);
  follow(true);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || send.disabled) return;

    send.disabled = input.disabled = mode.disabled = true;
    status.textContent = "";
    setEmpty(false);
    thread.append(h("div", { class: "user-msg", dir: "auto", text }));
    follow(true);
    input.value = "";
    autosize();

    const agents = mode.value === "team" ? TEAM : [mode.value];
    let turn = null;
    try {
      if (!sessionId) {
        const s = await api("/sessions", { method: "POST", body: JSON.stringify({}) });
        sessionId = s.id;
        storeSession(sessionId);
        history.replaceState(null, "", `#/chat/${sessionId}`);
      }
      await streamPost(`/sessions/${sessionId}/stream`, { message: text, agents }, (event, data) => {
        if (event === "user_message_saved") {
          turn = createTurn({ team: data.team, agents: data.agents?.length ? data.agents : agents });
          thread.append(turn.el);
          window.dispatchEvent(new Event("chats-changed"));
        } else if (!turn) {
          return;
        } else if (event === "agent_start") turn.start(data);
        else if (event === "thinking_chunk") turn.thinking(data);
        else if (event === "content_chunk") turn.content(data);
        else if (event === "agent_done") turn.done(data);
        else if (event === "error") turn.error(`${agentName(data.agent_slug)}: ${data.message}`);
        follow();
      });
    } catch (err) {
      status.textContent = "Request failed: " + err.message;
    }
    turn?.finish();
    follow();
    send.disabled = input.disabled = mode.disabled = false;
    input.focus();
  });

  input.focus();
}
