import { api } from "../js/api.js";
import { AGENTS, agentColor, agentName } from "../js/agents.js";
import { addStrings, duration, language, t } from "../js/i18n.js";
import { h, renderAnswer } from "../js/render.js";
import { streamPost } from "../js/sse.js";

const TEAM = ["icp", "auditor", "privacy", "coordinator"];

const SUGGESTIONS = {
  en: [
    "Which authority can order a government AI screening system to be paused, and on what legal basis?",
    "Does UAE PDPL Article (18) give visa applicants a right to object to automated decisions?",
    "What do international references require for human oversight of high-risk AI in public services?",
    "Does the data protection law apply to government entities?",
  ],
  ar: [
    "ما الجهة المخوّلة بإيقاف نظام فرز حكومي يعمل بالذكاء الاصطناعي، وما الأساس القانوني لذلك؟",
    "هل تمنح المادة (18) من قانون حماية البيانات الشخصية طالبي التأشيرات حق الاعتراض على القرارات الآلية؟",
    "ما متطلبات المراجع الدولية للإشراف البشري على أنظمة الذكاء الاصطناعي عالية المخاطر في الخدمات العامة؟",
    "هل تنطبق أحكام قانون حماية البيانات الشخصية على الجهات الحكومية؟",
  ],
};

addStrings({
  en: {
    "chat.title": "What should the agents look into?",
    "chat.mode": "Who answers",
    "chat.mode.team": "Team · 4 agents",
    "chat.mode.only": "{name} only",
    "chat.placeholder": "Message Mathuq…",
    "chat.message": "Message",
    "chat.send": "Send",
    "chat.team": "Mathuq team",
    "chat.flow": "{names} → Coordinator",
    "chat.status.team": "The team is thinking",
    "chat.status.single": "Thinking",
    "chat.status.writing": "The Coordinator is writing the final answer",
    "chat.status.reasoning": "{name} is reasoning",
    "chat.step.reasoning": "reasoning",
    "chat.step.reading": "reading the team's assessments",
    "chat.step.drafting": "drafting an assessment",
    "chat.step.noReasoning": "No reasoning was recorded for this step.",
    "chat.step.failed": "could not answer: the model stopped",
    "chat.step.final": "wrote the final answer",
    "chat.step.answered": "answered from {n} sources",
    "chat.step.assessed": "assessed from {n} sources",
    "chat.failed": "The model stopped before answering. Please ask again.",
    "chat.readAssessment": "Read the assessment",
    "chat.cot": "Chain of thought",
    "chat.cotTime": "Chain of thought · {time}",
    "chat.agentCount": "· {n} agents",
    "chat.noAnswer": "No answer was produced.",
    "chat.teamSources": "Sources consulted by the team",
    "chat.requestFailed": "The request failed: {error}",
  },
  ar: {
    "chat.title": "ما الذي تريد من الوكلاء دراسته؟",
    "chat.mode": "من يجيب",
    "chat.mode.team": "الفريق · 4 وكلاء",
    "chat.mode.only": "{name} فقط",
    "chat.placeholder": "اكتب رسالتك إلى موثوق…",
    "chat.message": "الرسالة",
    "chat.send": "إرسال",
    "chat.team": "فريق موثوق",
    "chat.flow": "{names} ← المنسّق",
    "chat.status.team": "الفريق يفكّر",
    "chat.status.single": "يفكّر",
    "chat.status.writing": "المنسّق يكتب الإجابة النهائية",
    "chat.status.reasoning": "{name} يحلّل",
    "chat.step.reasoning": "يحلّل",
    "chat.step.reading": "يقرأ تقييمات الفريق",
    "chat.step.drafting": "يصوغ تقييمه",
    "chat.step.noReasoning": "لم يُسجَّل تحليل لهذه الخطوة.",
    "chat.step.failed": "تعذّر الرد: توقف النموذج",
    "chat.step.final": "كتب الإجابة النهائية",
    "chat.step.answered": "أجاب استناداً إلى {n} مصادر",
    "chat.step.assessed": "قيّم استناداً إلى {n} مصادر",
    "chat.failed": "توقف النموذج قبل الإجابة. يرجى إعادة السؤال.",
    "chat.readAssessment": "عرض التقييم",
    "chat.cot": "سلسلة التفكير",
    "chat.cotTime": "سلسلة التفكير · {time}",
    "chat.agentCount": "· {n} وكلاء",
    "chat.noAnswer": "لم تُنتَج إجابة.",
    "chat.teamSources": "المصادر التي اعتمد عليها الفريق",
    "chat.requestFailed": "فشل الطلب: {error}",
  },
});

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

const MODE_KEY = "chatMode";

/** Start the next new chat with one agent (or the team) selected. */
export function presetMode(mode) {
  try {
    sessionStorage.setItem(MODE_KEY, mode);
  } catch {
    /* storage unavailable */
  }
}

function takePresetMode() {
  try {
    const mode = sessionStorage.getItem(MODE_KEY);
    sessionStorage.removeItem(MODE_KEY);
    return mode;
  } catch {
    return null;
  }
}

const logo = () => [
  h("img", { class: "logo logo-on-light", src: "/logo-black.svg", alt: "", width: 28, height: 28 }),
  h("img", { class: "logo logo-on-dark", src: "/logo-white.svg", alt: "", width: 28, height: 28 }),
];

/**
 * One assistant turn. Specialists' reasoning and assessments go into a collapsible
 * "Thinking" panel; the final answer (Coordinator synthesis in team mode) is shown below it.
 */
function createTurn({ team, agents, conversation = false }) {
  const started = Date.now();
  const statusText = h("span", { text: t(team ? "chat.status.team" : "chat.status.single") });
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
        h("b", { text: conversation ? t("brand") : team ? t("chat.team") : agentName(agents[0]) }),
        team && !conversation ? h("small", { text: t("chat.flow", { names }) }) : null,
      ),
      // A greeting is answered directly, so there is no chain of thought to show.
      conversation ? null : think,
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
        ? t("chat.status.writing")
        : t("chat.status.reasoning", { name: agentName(data.agent_slug, data.agent_name) });
      step(data.agent_slug, t(data.is_synthesis ? "chat.step.reading" : "chat.step.reasoning"));
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
        s.meta.textContent = t("chat.step.drafting");
      }
    },
    done(data) {
      const s = bySlug[data.agent_slug];
      if (!s) return;
      s.node.dataset.state = "done";
      if (data.thinking) s.text.textContent = data.thinking;
      if (!s.text.textContent.trim()) s.text.replaceWith(h("div", { class: "step-empty", text: t("chat.step.noReasoning") }));
      const text = data.content || s.content;
      if (data.interrupted || /^\(stream interrupted/.test(text)) {
        s.node.dataset.state = "failed";
        s.meta.textContent = t("chat.step.failed");
        if (!team || data.is_synthesis) answer.replaceChildren(h("div", { class: "notice danger", text: t("chat.failed") }));
        return;
      }
      const refs = data.references || [];
      const isFinal = !team || data.is_synthesis;
      if (isFinal) {
        s.meta.textContent = team ? t("chat.step.final") : t("chat.step.answered", { n: refs.length });
        answer.replaceChildren(
          renderAnswer(text, team ? dedupe(references) : refs, {
            sourcesLabel: team ? t("chat.teamSources") : t("answer.sources"),
          }),
        );
      } else {
        references.push(...refs);
        s.meta.textContent = t("chat.step.assessed", { n: refs.length });
        s.out.append(
          h("details", { class: "step-answer" }, h("summary", { text: t("chat.readAssessment") }), renderAnswer(text, refs)),
        );
      }
    },
    error(message) {
      answer.append(h("div", { class: "notice danger", text: message }));
    },
    finish() {
      clearInterval(tick);
      const count = Object.keys(bySlug).length;
      if (conversation) {
        if (!answer.childElementCount) answer.append(h("p", { class: "muted", text: t("chat.noAnswer") }));
        return;
      }
      statusText.textContent = t("chat.cotTime", { time: duration(Date.now() - started) });
      timer.textContent = team ? t("chat.agentCount", { n: count }) : "";
      think.classList.add("finished");
      if (!answer.childElementCount) answer.append(h("p", { class: "muted", text: t("chat.noAnswer") }));
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
  const conversation = items.every((i) => i.meta.source === "chat_conversation");
  const team = items.length > 1;
  const turn = createTurn({ team, agents: items.map((i) => i.slug), conversation });
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
  const label = turn.el.querySelector(".think summary span:nth-child(2)");
  if (label) label.textContent = t("chat.cot");
  return turn.el;
}

export async function renderChat(container, params = {}) {
  const thread = h("div", { class: "thread", "aria-live": "polite" });
  const empty = h("div", { class: "chat-empty" },
    h("h1", { text: t("chat.title") }),
    h("div", { class: "starter-grid" },
      SUGGESTIONS[language()].map((text) => h("button", { class: "starter", type: "button", dir: "auto", text, onclick: () => { input.value = text; autosize(); input.focus(); } })),
    ),
  );
  const status = h("p", { class: "error", role: "alert" });
  const mode = h("select", { class: "mode-select", "aria-label": t("chat.mode") },
    h("option", { value: "team", text: t("chat.mode.team") }),
    Object.keys(AGENTS).map((slug) => h("option", { value: slug, text: t("chat.mode.only", { name: agentName(slug) }) })),
  );
  const preset = takePresetMode();
  if (preset && (preset === "team" || AGENTS[preset])) mode.value = preset;
  const input = h("textarea", { class: "composer-input", rows: 1, dir: "auto", placeholder: t("chat.placeholder"), "aria-label": t("chat.message") });
  const send = h("button", { class: "send-btn", type: "submit", "aria-label": t("chat.send"), html: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M12 4l-7 7h4.5v9h5v-9H19z"/></svg>' });
  const form = h("form", { class: "composer2" },
    h("div", { class: "chat-col" },
      h("div", { class: "composer-box" }, input, h("div", { class: "composer-row2" }, mode, h("span", { style: { flex: 1 } }), send)),
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
    status.textContent = t("common.loadFailed", { error: err.message });
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
          turn = createTurn({
            team: data.team,
            agents: data.agents?.length ? data.agents : agents,
            conversation: data.conversation,
          });
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
      status.textContent = t("chat.requestFailed", { error: err.message });
    }
    turn?.finish();
    follow();
    send.disabled = input.disabled = mode.disabled = false;
    input.focus();
  });

  input.focus();
}
