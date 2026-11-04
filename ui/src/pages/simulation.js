import { api } from "../js/api.js";
import { agentColor, agentInitials, agentName, agentRole } from "../js/agents.js";
import { addStrings, duration, language, num, t } from "../js/i18n.js";
import { h, renderAnswer, textDir } from "../js/render.js";
import { statusLabel } from "./scenarios.js";

addStrings({
  en: {
    "run.back": "Simulations",
    "run.release": "Release event {n}",
    "run.working": "Agents are working…",
    "run.complete": "All events released",
    "run.progress": "{n} of {total} events released",
    "run.audit": "Audit log",
    "run.gapsLink": "Gap report",
    "run.timeline": "Timeline",
    "run.event": "Event {n}",
    "run.controversy": "Contested decision",
    "run.sequential": "Sequential",
    "run.to": "Released to",
    "run.flow.independent": "The agencies assess independently, then the Coordinator reconciles them.",
    "run.flow.sequential": "Each agency receives the previous agency's assessment before responding.",
    "run.empty": "No event has been released yet. Release the first event to brief the agents.",
    "run.pending": "{name} is assessing…",
    "run.pendingSynthesis": "The Coordinator will reconcile the assessments",
    "run.synthesis": "Coordinator synthesis",
    "run.synthesisOf": "reconciles {names}",
    "run.respondingTo": "responding to {names}",
    "run.reasoning": "Reasoning",
    "run.missing": "No assessment was recorded for part of this event.",
    "run.missingHelp": "The run was interrupted before every agent answered.",
    "run.rerun": "Complete this event",
    "run.failed": "The request failed: {error}",
    "run.agentFailed": "{name} could not answer: {error}",
    "gaps.title": "Policy gap report",
    "gaps.subtitle": "Gaps surfaced by the agents, each mapped to an international reference retrieved from the knowledge base.",
    "gaps.build": "Build the report",
    "gaps.rebuild": "Rebuild the report",
    "gaps.building": "Analysing the assessments…",
    "gaps.needsAssessments": "Available once at least one event has been assessed.",
    "gaps.failed": "The report could not be built: {error}",
    "gaps.practice": "Global practice",
    "gaps.evidence": "Raised by: {text}",
    "severity.critical": "Critical",
    "severity.high": "High",
    "severity.medium": "Medium",
    "severity.low": "Low",
    "gap.policy": "Policy",
    "gap.legal": "Legislative",
    "gap.standards": "Standards",
    "gap.implementation": "Implementation",
    "gap.coordination": "Coordination",
  },
  ar: {
    "run.back": "المحاكاة",
    "run.release": "إطلاق الحدث {n}",
    "run.working": "الوكلاء يعملون…",
    "run.complete": "أُطلقت جميع الأحداث",
    "run.progress": "أُطلق {n} من {total} أحداث",
    "run.audit": "سجل التدقيق",
    "run.gapsLink": "تقرير الفجوات",
    "run.timeline": "التسلسل الزمني",
    "run.event": "الحدث {n}",
    "run.controversy": "قرار متنازع عليه",
    "run.sequential": "تسلسلي",
    "run.to": "أُرسل إلى",
    "run.flow.independent": "تقيّم الجهات بشكل مستقل، ثم يوفّق المنسّق بين تقييماتها.",
    "run.flow.sequential": "تتلقى كل جهة تقييم الجهة السابقة قبل أن ترد.",
    "run.empty": "لم يُطلق أي حدث بعد. أطلق الحدث الأول لإحاطة الوكلاء.",
    "run.pending": "{name} يقيّم…",
    "run.pendingSynthesis": "سيوفّق المنسّق بين التقييمات",
    "run.synthesis": "خلاصة المنسّق",
    "run.synthesisOf": "يوفّق بين {names}",
    "run.respondingTo": "ردّاً على {names}",
    "run.reasoning": "التحليل",
    "run.missing": "لم يُسجَّل تقييم لجزء من هذا الحدث.",
    "run.missingHelp": "انقطع التشغيل قبل أن يجيب جميع الوكلاء.",
    "run.rerun": "إكمال هذا الحدث",
    "run.failed": "فشل الطلب: {error}",
    "run.agentFailed": "تعذّر على {name} الرد: {error}",
    "gaps.title": "تقرير الفجوات التنظيمية",
    "gaps.subtitle": "الفجوات التي كشفها الوكلاء، وكلٌّ منها مرتبط بمرجع دولي مسترجع من قاعدة المعرفة.",
    "gaps.build": "إعداد التقرير",
    "gaps.rebuild": "إعادة إعداد التقرير",
    "gaps.building": "جارٍ تحليل التقييمات…",
    "gaps.needsAssessments": "يتاح بعد تقييم حدث واحد على الأقل.",
    "gaps.failed": "تعذّر إعداد التقرير: {error}",
    "gaps.practice": "الممارسة الدولية",
    "gaps.evidence": "أثارها: {text}",
    "severity.critical": "حرجة",
    "severity.high": "عالية",
    "severity.medium": "متوسطة",
    "severity.low": "منخفضة",
    "gap.policy": "سياسات",
    "gap.legal": "تشريعية",
    "gap.standards": "معايير",
    "gap.implementation": "تطبيق",
    "gap.coordination": "تنسيق",
  },
});

const ar = () => language() === "ar";
const eventTitle = (e) => (ar() && e.title_ar) || e.title;
const eventText = (e) => (ar() && e.content_ar) || e.content;
const names = (slugs) => (slugs || []).map((s) => agentName(s)).join(ar() ? "، " : ", ");

function pending(slug, label) {
  const started = Date.now();
  const time = h("small", { class: "pending-time", text: "" });
  const el = h("div", { class: "pending", "--agent": agentColor(slug), role: "status" },
    h("span", { class: "pulse" }),
    h("div", { class: "pending-main" }, h("b", { text: label }), h("div", { class: "skeleton", style: { width: "65%" } })),
    time,
  );
  const timer = setInterval(() => {
    if (!el.isConnected) return clearInterval(timer);
    time.textContent = duration(Date.now() - started);
  }, 1000);
  return el;
}

/** One agent's assessment: header, answer, reasoning trace and sources. */
function assessmentCard(m, agentsById) {
  const agent = agentsById[m.agent_id];
  const slug = agent?.slug;
  const meta = m.message_metadata || {};
  const synthesis = meta.is_synthesis;
  const subtitle = synthesis
    ? t("run.synthesisOf", { names: names(meta.responding_to) })
    : meta.responding_to?.length
      ? t("run.respondingTo", { names: names(meta.responding_to) })
      : agentRole(slug, agent?.role);
  return h("article", { class: "assessment" + (synthesis ? " synthesis" : ""), "--agent": agentColor(slug) },
    synthesis ? h("div", { class: "synth-banner", text: t("run.synthesis") }) : null,
    h("header", { class: "assessment-head" },
      h("span", { class: "avatar", text: agentInitials(slug, agent?.name) }),
      h("div", {}, h("b", { text: agentName(slug, agent?.name) }), h("small", { text: subtitle })),
    ),
    h("div", { class: "assessment-body" }, renderAnswer(m.content, meta.references || [])),
    m.thinking_trace
      ? h("details", { class: "trace-box" },
          h("summary", { text: t("run.reasoning") }),
          h("div", { class: "trace", dir: textDir(m.thinking_trace), text: m.thinking_trace }),
        )
      : null,
  );
}

function gapCard(gap) {
  const [head, ...rest] = gap.description.split(/:\s(.+)/s);
  const hasTitle = rest.length > 0 && head.length < 140;
  let body = hasTitle ? rest.join("") : gap.description;
  let evidence = "";
  const parts = body.split(/\nEvidence:\s*/);
  if (parts.length > 1) [body, evidence] = parts;
  const title = hasTitle ? head : body;
  return h("article", { class: "gap", "data-sev": gap.severity },
    h("div", { class: "gap-tags" },
      h("span", { class: "sev", text: t(`severity.${gap.severity}`) }),
      h("span", { class: "tag", text: t(`gap.${gap.gap_type}`) }),
    ),
    h("h3", { dir: textDir(title), text: title }),
    hasTitle ? h("p", { dir: textDir(body), text: body }) : null,
    gap.global_best_practice
      ? h("div", { class: "practice" },
          h("b", { text: t("gaps.practice") }),
          h("p", { dir: textDir(gap.global_best_practice), text: gap.global_best_practice }),
        )
      : null,
    gap.global_references?.length
      ? h("ul", { class: "gap-refs" },
          gap.global_references.map((r) =>
            h("li", { dir: "auto", text: [r.title, r.section, r.page ? `p. ${r.page}` : null].filter(Boolean).join(" · ") }),
          ),
        )
      : null,
    evidence ? h("small", { class: "muted", dir: "auto", text: t("gaps.evidence", { text: evidence }) }) : null,
  );
}

export async function renderSimulation(container, { id }) {
  const title = h("h1", { class: "run-title" });
  const pill = h("span", { class: "status-pill" });
  const bar = h("i");
  const progress = h("small", { class: "muted" });
  const release = h("button", { class: "btn primary block", type: "button" });
  const timeline = h("ol", { class: "timeline" });
  const status = h("p", { class: "error", role: "alert" });
  const feed = h("div", { class: "feed" });
  const gapSection = h("section", { class: "gap-section", id: "gaps" });

  container.append(
    h("div", { class: "run" },
      h("aside", { class: "run-side" },
        h("a", { class: "back-link", href: "/simulations", text: t("run.back") }),
        h("div", { class: "panel run-card" },
          title,
          h("div", { class: "run-meta" }, pill, progress),
          h("div", { class: "progress", role: "progressbar" }, bar),
          release,
          h("div", { class: "run-links" },
            h("a", { class: "btn sm", href: `/audit/${id}`, text: t("run.audit") }),
            h("button", { class: "btn sm", type: "button", text: t("run.gapsLink"), onclick: () => gapSection.scrollIntoView({ behavior: "smooth" }) }),
          ),
        ),
        h("div", { class: "panel" }, h("h2", { class: "side-title", text: t("run.timeline") }), timeline),
      ),
      h("div", { class: "run-main" }, status, feed, gapSection),
    ),
  );

  const state = { timeline: null, messages: [], gaps: [], agentsById: {} };
  let busy = false;

  try {
    const [tl, agents, messages, gaps] = await Promise.all([
      api(`/sessions/${id}/timeline`),
      api("/agents"),
      api(`/sessions/${id}/messages`),
      api(`/sessions/${id}/gaps`).catch(() => []),
    ]);
    for (const a of agents) state.agentsById[a.id] = a;
    Object.assign(state, { timeline: tl, messages, gaps });
  } catch (err) {
    status.textContent = t("common.loadFailed", { error: err.message });
    release.hidden = true;
    return;
  }

  async function reload() {
    const [tl, messages] = await Promise.all([api(`/sessions/${id}/timeline`), api(`/sessions/${id}/messages`)]);
    Object.assign(state, { timeline: tl, messages });
  }

  function drawSide() {
    const tl = state.timeline;
    title.textContent = (ar() && tl.scenario_title_ar) || tl.scenario_title || tl.scenario_slug;
    title.dir = textDir(title.textContent);
    pill.dataset.status = tl.status;
    pill.textContent = statusLabel(tl.status);
    const released = tl.events.filter((e) => e.released).length;
    bar.style.width = `${(released / Math.max(tl.total_events, 1)) * 100}%`;
    progress.textContent = t("run.progress", { n: num(released), total: num(tl.total_events) });
    const next = tl.events.find((e) => !e.released);
    release.disabled = busy || !next;
    release.textContent = busy ? t("run.working") : next ? t("run.release", { n: num(next.sequence) }) : t("run.complete");

    timeline.replaceChildren(
      ...tl.events.map((e) =>
        h("li", { class: e.released ? "released" : e === next ? "next" : "" },
          h("span", { class: "dot", text: e.released ? "✓" : num(e.sequence) }),
          h("div", {},
            e.released
              ? h("button", { class: "link", type: "button", dir: textDir(eventTitle(e)), text: eventTitle(e), onclick: () => feed.querySelector(`[data-seq="${e.sequence}"]`)?.scrollIntoView({ behavior: "smooth" }) })
              : h("span", { dir: textDir(eventTitle(e)), text: eventTitle(e) }),
            h("div", { class: "mini-agents" }, (e.target_agent_roles || []).map((s) => h("i", { "--agent": agentColor(s), title: agentName(s) }))),
          ),
        ),
      ),
    );
  }

  function eventCard(e) {
    const targets = e.target_agent_roles || [];
    const flow = targets.length > 1
      ? h("p", { class: "flow-note", text: t(e.sequential ? "run.flow.sequential" : "run.flow.independent") })
      : null;
    return h("div", { class: "event-card" + (e.scenario_type === "controversy" ? " controversy" : "") },
      h("header", {},
        h("span", { class: "event-seq", text: t("run.event", { n: num(e.sequence) }) }),
        e.scenario_type === "controversy" ? h("span", { class: "tag warn", text: t("run.controversy") }) : null,
        e.sequential ? h("span", { class: "tag", text: t("run.sequential") }) : null,
      ),
      h("h3", { dir: textDir(eventTitle(e)), text: eventTitle(e) }),
      eventText(e) ? h("p", { dir: textDir(eventText(e)), text: eventText(e) }) : null,
      h("div", { class: "event-targets" },
        h("small", { text: t("run.to") }),
        targets.map((s) => h("span", { class: "chip", "--agent": agentColor(s) }, h("i"), agentName(s))),
      ),
      flow,
    );
  }

  function eventIsIncomplete(e, msgs) {
    const targets = e.target_agent_roles || [];
    const answered = new Set(msgs.filter((m) => !m.message_metadata?.is_synthesis).map((m) => state.agentsById[m.agent_id]?.slug));
    const needsSynthesis = targets.length > 1 && !targets.includes("coordinator");
    const hasSynthesis = msgs.some((m) => m.message_metadata?.is_synthesis);
    return targets.some((s) => !answered.has(s)) || (needsSynthesis && !hasSynthesis);
  }

  function drawFeed() {
    const released = state.timeline.events.filter((e) => e.released);
    if (!released.length) {
      feed.replaceChildren(h("div", { class: "empty", text: t("run.empty") }));
      return;
    }
    feed.replaceChildren(
      ...released.map((e) => {
        const msgs = state.messages.filter((m) => m.role === "assistant" && m.message_metadata?.event_sequence === e.sequence);
        const incomplete = !busy && eventIsIncomplete(e, msgs);
        return h("section", { class: "event", "data-seq": e.sequence },
          eventCard(e),
          msgs.map((m) => assessmentCard(m, state.agentsById)),
          incomplete
            ? h("div", { class: "notice warn" },
                h("div", { class: "grow" }, h("b", { text: t("run.missing") }), h("p", { text: t("run.missingHelp") })),
                h("button", { class: "btn sm", type: "button", text: t("run.rerun"), onclick: () => runEvent(e, `/sessions/${id}/events/${e.sequence}/run`) }),
              )
            : null,
        );
      }),
    );
  }

  function drawGaps(mode = "idle", error = "") {
    const assessed = state.messages.some((m) => m.role === "assistant");
    const button = h("button", {
      class: "btn" + (state.gaps.length ? "" : " primary"),
      type: "button",
      text: t(state.gaps.length ? "gaps.rebuild" : "gaps.build"),
      disabled: mode === "building" || busy || !assessed,
      onclick: buildGaps,
    });
    gapSection.replaceChildren(
      h("header", { class: "gap-head" },
        h("div", {}, h("h2", { text: t("gaps.title") }), h("p", { class: "muted", text: t("gaps.subtitle") })),
        button,
      ),
      error ? h("div", { class: "notice danger", text: error }) : null,
      mode === "building"
        ? pending("coordinator", t("gaps.building"))
        : state.gaps.length
          ? h("div", { class: "gaps" }, state.gaps.map(gapCard))
          : assessed
            ? null
            : h("p", { class: "muted", text: t("gaps.needsAssessments") }),
    );
  }

  async function buildGaps() {
    drawGaps("building");
    try {
      state.gaps = await api(`/sessions/${id}/gaps?language=${language()}`, { method: "POST" });
      drawGaps();
    } catch (err) {
      drawGaps("idle", t("gaps.failed", { error: err.message }));
    }
  }

  async function runEvent(e, path) {
    if (busy) return;
    busy = true;
    status.textContent = "";
    drawSide();
    drawGaps();
    const targets = e.target_agent_roles || [];
    const section = h("section", { class: "event", "data-seq": e.sequence },
      eventCard(e.released ? e : { ...e, content: null, content_ar: null }),
      targets.map((s) => pending(s, t("run.pending", { name: agentName(s) }))),
      targets.length > 1 && !targets.includes("coordinator") ? pending("coordinator", t("run.pendingSynthesis")) : null,
    );
    const existing = feed.querySelector(`[data-seq="${e.sequence}"]`);
    feed.querySelector(".empty")?.remove();
    if (existing) existing.replaceWith(section);
    else feed.append(section);
    section.scrollIntoView({ behavior: "smooth", block: "start" });

    try {
      const r = await api(path, { method: "POST", body: JSON.stringify({ auto_run: true, language: language() }) });
      const failed = (r.assessments || []).filter((a) => a.error);
      if (failed.length) {
        status.textContent = failed.map((a) => t("run.agentFailed", { name: agentName(a.agent_slug), error: a.error })).join(" · ");
      }
    } catch (err) {
      status.textContent = t("run.failed", { error: err.message });
    }
    try {
      await reload();
    } catch {
      /* keep the previous state */
    }
    busy = false;
    drawSide();
    drawFeed();
    drawGaps();
    feed.querySelector(`[data-seq="${e.sequence}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  release.addEventListener("click", () => {
    const next = state.timeline.events.find((e) => !e.released);
    if (next) runEvent(next, `/sessions/${id}/advance`);
  });

  drawSide();
  drawFeed();
  drawGaps();
}
