import { api } from "../js/api.js";
import { agentColor, agentName } from "../js/agents.js";
import { h, renderGap, renderMessage, renderPending } from "../js/render.js";

export async function renderSimulation(container, { id }) {
  const title = h("h2", { text: "Loading…" });
  const statusPill = h("span", { class: "status-pill", text: "…" });
  const progressBar = h("i", { style: { width: "0%" } });
  const progressText = h("small", { class: "muted" });
  const advance = h("button", { class: "btn primary", type: "button", text: "Release next event" });
  const hint = h("small", { class: "muted", text: "Agents run on a local LLM. Each assessment can take a few minutes." });
  const timeline = h("ol", { class: "timeline" });
  const status = h("p", { class: "error", role: "alert" });
  const feed = h("div", { class: "feed" });
  const gapSection = h("section", { class: "event" });

  container.append(
    h("div", { class: "sim" },
      h("aside", { class: "sim-side" },
        h("div", { class: "panel panel-pad", style: { display: "flex", flexDirection: "column", gap: "12px" } },
          h("div", { class: "eyebrow", text: "Simulation" }),
          title,
          h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, statusPill, progressText),
          h("div", { class: "progress", role: "progressbar", "aria-label": "Events released" }, progressBar),
          advance,
          hint,
          h("div", { class: "card-actions" },
            h("a", { class: "btn sm", href: `#/audit/${id}`, text: "Audit log" }),
            h("button", { class: "btn sm ghost", type: "button", text: "Gap report ↓", onclick: () => gapSection.scrollIntoView({ behavior: "smooth" }) }),
          ),
        ),
        h("div", { class: "panel panel-pad" }, h("h3", { text: "Event timeline", style: { marginBottom: "10px" } }), timeline),
      ),
      h("div", { class: "feed" }, status, feed, gapSection),
    ),
  );

  let state = { timeline: null, agentsById: {}, messages: [], gaps: [] };
  let busy = false;

  try {
    const [t, agents, messages, gaps] = await Promise.all([
      api(`/sessions/${id}/timeline`),
      api("/agents"),
      api(`/sessions/${id}/messages`),
      api(`/sessions/${id}/gaps`).catch(() => []),
    ]);
    for (const a of agents) state.agentsById[a.id] = a;
    state = { ...state, timeline: t, messages, gaps };
  } catch (err) {
    status.textContent = "Could not load this session: " + err.message;
    advance.disabled = true;
    return;
  }

  function drawSide() {
    const t = state.timeline;
    title.textContent = t.scenario_title || t.scenario_slug;
    statusPill.dataset.status = t.status;
    statusPill.textContent = t.status;
    const released = t.events.filter((e) => e.released).length;
    progressBar.style.width = `${(released / Math.max(t.total_events, 1)) * 100}%`;
    progressText.textContent = `${released} of ${t.total_events} events released`;

    timeline.innerHTML = "";
    const nextSeq = t.events.find((e) => !e.released)?.sequence;
    for (const e of t.events) {
      const li = h("li", { class: e.released ? "released" : e.sequence === nextSeq ? "next" : "" },
        h("span", { class: "dot", text: e.released ? "✓" : e.sequence }),
        h("div", {},
          e.released
            ? h("a", { href: `#/session/${id}`, text: e.title, onclick: (ev) => { ev.preventDefault(); feed.querySelector(`[data-seq="${e.sequence}"]`)?.scrollIntoView({ behavior: "smooth" }); } })
            : h("span", { class: "t", text: e.title }),
          h("div", { class: "agents-mini" }, (e.target_agent_roles || []).map((s) => h("i", { "--agent": agentColor(s), title: agentName(s) }))),
        ),
      );
      timeline.append(li);
    }

    const done = t.status === "completed" || !nextSeq;
    advance.disabled = busy || done;
    advance.textContent = done ? "Scenario complete" : busy ? "Agents are working…" : `Release event ${nextSeq}`;
    hint.hidden = done;
  }

  function eventCard(e) {
    const controversy = e.scenario_type === "controversy";
    const targets = e.target_agent_roles || [];
    return h("div", { class: "event-card" + (controversy ? " controversy" : "") },
      h("header", {},
        h("span", { class: "seq", text: `EVENT ${e.sequence}` }),
        h("h3", { text: e.title }),
        controversy ? h("span", { class: "tag warn", text: "Controversy" }) : null,
        e.sequential ? h("span", { class: "tag", text: "Sequential hand-off" }) : null,
      ),
      e.content ? h("p", { text: e.content }) : null,
      h("div", { class: "tags", style: { marginTop: "10px" } },
        h("small", { class: "muted", text: "Released to:" }),
        targets.map((s) => h("span", { class: "tag", "--agent": agentColor(s) }, h("i"), agentName(s))),
      ),
    );
  }

  function flowNote(e) {
    const targets = e.target_agent_roles || [];
    if (targets.length < 2) return null;
    if (e.sequential) return h("div", { class: "flow-note", text: "Each agent receives the previous agent's assessment before responding." });
    if (targets.includes("coordinator")) return h("div", { class: "flow-note", text: "Agents assess independently." });
    return h("div", { class: "flow-note", text: "Agents assess independently, without seeing each other's drafts. The Coordinator then reconciles them." });
  }

  function messageView(m) {
    const agent = state.agentsById[m.agent_id];
    const meta = m.message_metadata || {};
    return renderMessage({
      agent_slug: agent?.slug,
      agent_name: agent?.name,
      role: agent?.role,
      content: m.content,
      thinking: m.thinking_trace,
      references: meta.references,
      is_synthesis: meta.is_synthesis,
      responding_to: meta.responding_to,
    });
  }

  function drawFeed() {
    feed.innerHTML = "";
    const released = state.timeline.events.filter((e) => e.released);
    if (!released.length) {
      feed.append(
        h("div", { class: "empty" },
          h("p", { text: "No events released yet." }),
          h("p", { class: "muted", text: "Release the first event to brief the agents. Later events stay hidden until released, as in a real incident." }),
        ),
      );
    }
    for (const e of released) {
      const msgs = state.messages.filter((m) => m.role === "assistant" && m.message_metadata?.event_sequence === e.sequence);
      const recovery = msgs.length
        ? null
        : h("div", { class: "notice warn" },
            h("div", { class: "grow" },
              h("b", { text: "No assessments were recorded for this event." }),
              h("p", { text: "The run was interrupted before the agents finished. Run them again for this event; nothing else changes." }),
            ),
            h("button", { class: "btn sm", type: "button", text: "Run agents", disabled: busy, onclick: () => runEvent(e, `/sessions/${id}/events/${e.sequence}/run`) }),
          );
      feed.append(
        h("section", { class: "event", "data-seq": e.sequence }, eventCard(e), flowNote(e), msgs.map(messageView), recovery),
      );
    }
  }

  function drawGaps(pending = false, error = "") {
    gapSection.innerHTML = "";
    const hasAssessments = state.messages.some((m) => m.role === "assistant");
    const button = h("button", {
      class: "btn" + (state.gaps.length ? "" : " primary"),
      type: "button",
      text: state.gaps.length ? "Rebuild gap report" : "Build gap report",
      disabled: pending || busy || !hasAssessments,
      onclick: buildGaps,
    });
    gapSection.append(
      h("div", { class: "event-card" },
        h("header", {},
          h("span", { class: "seq", text: "REPORT" }),
          h("h3", { text: "Policy gap report" }),
          h("span", { style: { flex: 1 } }),
          button,
        ),
        h("p", { text: "Domain-level gaps surfaced by the agents — unclear responsibilities, missing standards, legislative and coordination gaps — each mapped to international practice retrieved from the knowledge base." }),
      ),
    );
    if (error) gapSection.append(h("div", { class: "notice danger", text: error }));
    if (pending) gapSection.append(renderPending("coordinator", "Analysing assessments against international references…"));
    else if (state.gaps.length) gapSection.append(h("div", { class: "gaps" }, state.gaps.map(renderGap)));
    else if (!hasAssessments) gapSection.append(h("p", { class: "muted", text: "Available once at least one event has been assessed." }));
  }

  async function buildGaps() {
    drawGaps(true);
    try {
      state.gaps = await api(`/sessions/${id}/gaps`, { method: "POST" });
      drawGaps();
    } catch (err) {
      drawGaps(false, "Gap extraction failed: " + err.message);
    }
  }

  advance.addEventListener("click", () => {
    const next = state.timeline.events.find((e) => !e.released);
    if (next) runEvent(next, `/sessions/${id}/advance`);
  });

  // Release (or re-run) one event: show a placeholder per agent while the backend works.
  async function runEvent(next, path) {
    if (busy) return;
    busy = true;
    status.textContent = "";
    drawSide();
    drawGaps();

    const targets = next.target_agent_roles || [];
    const section = h("section", { class: "event", "data-seq": next.sequence },
      eventCard(next.released ? next : { ...next, content: null }),
      flowNote(next),
      targets.map((s) => renderPending(s)),
      targets.length > 1 && !targets.includes("coordinator")
        ? renderPending("coordinator", "Coordinator will synthesize once all assessments are in")
        : null,
    );
    feed.querySelector(".empty")?.remove();
    const existing = feed.querySelector(`[data-seq="${next.sequence}"]`);
    if (existing) existing.replaceWith(section);
    else feed.append(section);
    section.scrollIntoView({ behavior: "smooth", block: "start" });

    try {
      const r = await api(path, { method: "POST", body: JSON.stringify({ auto_run: true }) });
      const [t, messages] = await Promise.all([api(`/sessions/${id}/timeline`), api(`/sessions/${id}/messages`)]);
      state.timeline = t;
      state.messages = messages;
      if (!r.event) status.textContent = r.message || "No more events.";
      const failed = (r.assessments || []).filter((a) => a.error);
      if (failed.length) status.textContent = failed.map((a) => `${agentName(a.agent_slug)}: ${a.error}`).join(" · ");
    } catch (err) {
      status.textContent = "Run failed: " + err.message;
      try {
        state.timeline = await api(`/sessions/${id}/timeline`);
        state.messages = await api(`/sessions/${id}/messages`);
      } catch {
        /* keep previous state */
      }
    }
    busy = false;
    drawSide();
    drawFeed();
    drawGaps();
    feed.querySelector(`[data-seq="${next.sequence}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  drawSide();
  drawFeed();
  drawGaps();
}
