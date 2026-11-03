import { api } from "../js/api.js";
import { agentColor } from "../js/agents.js";

export async function renderAudit(container, { id }) {
  container.innerHTML = `
    <h1>Audit Log</h1>
    <div class="toolbar">
      <select id="f-action">
        <option value="">All actions</option>
        <option value="retrieval">retrieval</option>
        <option value="reasoning">reasoning</option>
        <option value="decision">decision</option>
      </select>
      <select id="f-agent"><option value="">All agents</option></select>
      <button id="export" class="btn" type="button">Export JSON</button>
      <a class="btn" href="#/session/${id}">Back to simulation</a>
    </div>
    <p id="status">Loading...</p>
    <table class="audit" hidden>
      <thead><tr><th>Action</th><th>Agent</th><th>Reasoning</th><th>References</th><th>Time</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>`;

  const status = container.querySelector("#status");
  const table = container.querySelector("table");
  const rows = container.querySelector("#rows");
  const fAction = container.querySelector("#f-action");
  const fAgent = container.querySelector("#f-agent");

  let logs = [];
  const agentsById = {};

  try {
    const [agents, data] = await Promise.all([
      api("/agents"),
      api(`/sessions/${id}/audit`),
    ]);
    for (const a of agents) {
      agentsById[a.id] = a;
      const opt = document.createElement("option");
      opt.value = a.slug;
      opt.textContent = a.name;
      fAgent.appendChild(opt);
    }
    logs = data;
  } catch (err) {
    status.textContent = "Could not load audit: " + err.message;
    return;
  }

  function draw() {
    rows.innerHTML = "";
    const shown = logs.filter((l) => {
      const slug = agentsById[l.agent_id]?.slug;
      return (!fAction.value || l.action === fAction.value) &&
             (!fAgent.value || slug === fAgent.value);
    });
    status.textContent = shown.length ? "" : "No records.";
    table.hidden = shown.length === 0;

    for (const l of shown) {
      const agent = agentsById[l.agent_id];
      const refs = (l.source_attributions || []).length;

      const tr = document.createElement("tr");
      tr.className = "clickable";
      tr.innerHTML = "<td></td><td></td><td dir='auto'></td><td></td><td></td>";
      tr.children[0].textContent = l.action;
      tr.children[1].textContent = agent ? agent.name : "-";
      if (agent) tr.children[1].style.color = agentColor(agent.slug);
      tr.children[2].textContent = (l.reasoning || "").slice(0, 80);
      if (refs) {
        tr.children[3].textContent = refs + " sources";
      } else {
        tr.children[3].innerHTML = "<span class='badge'>No sources (RAG pending)</span>";
      }
      tr.children[4].textContent = new Date(l.created_at).toLocaleTimeString();

      const detail = document.createElement("tr");
      detail.hidden = true;
      detail.innerHTML = "<td colspan='5'><pre class='thinking' dir='auto'></pre></td>";
      detail.querySelector("pre").textContent =
        (l.reasoning || "(empty)") +
        "\n\n--- source_attributions ---\n" +
        JSON.stringify(l.source_attributions || [], null, 2);

      tr.addEventListener("click", () => { detail.hidden = !detail.hidden; });
      rows.append(tr, detail);
    }
  }

  fAction.addEventListener("change", draw);
  fAgent.addEventListener("change", draw);

  container.querySelector("#export").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `audit-${id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });

  draw();
}