import { api } from "../js/api.js";
import { agentColor } from "../js/agents.js";

export async function renderSimulation(container, { id }) {
  container.innerHTML = `
    <div class="sim">
      <aside class="panel">
        <h2>Timeline</h2>
        <ol id="timeline" class="timeline"></ol>
      </aside>
      <section class="panel">
        <div class="sim-head">
          <h2>Assessments</h2>
          <button id="advance" class="btn primary" type="button">Advance to Next Event</button>
          <a class="btn" href="#/audit/${id}">View Full Audit</a>
        </div>
        <p id="status" class="error"></p>
        <div id="chat" class="chat"></div>
      </section>
      <aside class="panel">
        <details open>
          <summary>Live Thinking</summary>
          <pre id="thinking" class="thinking">Nothing yet.</pre>
        </details>
      </aside>
    </div>`;

  const timelineEl = container.querySelector("#timeline");
  const chat = container.querySelector("#chat");
  const thinking = container.querySelector("#thinking");
  const statusEl = container.querySelector("#status");
  const button = container.querySelector("#advance");

  async function loadTimeline() {
    const t = await api(`/sessions/${id}/timeline`);
    timelineEl.innerHTML = "";
    for (const e of t.events) {
      const li = document.createElement("li");
      li.className = e.released ? "done" : "";
      li.textContent = (e.released ? "✓ " : "○ ") + e.sequence + ". " + e.title;
      timelineEl.appendChild(li);
    }
    if (t.status === "completed") {
      button.disabled = true;
      button.textContent = "Scenario completed";
    }
  }

  function addAssessment(eventTitle, a) {
    const bubble = document.createElement("article");
    bubble.className = "bubble";
    bubble.style.setProperty("--agent", agentColor(a.agent_slug));
    bubble.innerHTML = "<small></small><b></b><p dir='auto'></p>";
    bubble.querySelector("small").textContent = eventTitle;
    bubble.querySelector("b").textContent = a.agent_name || a.agent_slug;
    bubble.querySelector("p").textContent = a.error
      ? "Error: " + a.error
      : a.content;
    chat.appendChild(bubble);
    if (a.thinking) thinking.textContent = a.thinking;
  }

  button.addEventListener("click", async () => {
    button.disabled = true;
    statusEl.textContent = "Agents are thinking...";
    try {
      const r = await api(`/sessions/${id}/advance`, {
        method: "POST",
        body: JSON.stringify({ auto_run: true }),
      });
      statusEl.textContent = "";
      if (r.event) {
        for (const a of r.assessments) addAssessment(r.event.title, a);
      } else {
        statusEl.textContent = r.message || "No more events.";
      }
      await loadTimeline();
    } catch (err) {
      statusEl.textContent = "Advance failed: " + err.message;
    }
    if (!button.textContent.startsWith("Scenario")) button.disabled = false;
  });

  try {
    await loadTimeline();
  } catch (err) {
    statusEl.textContent = "Could not load session: " + err.message;
  }
}