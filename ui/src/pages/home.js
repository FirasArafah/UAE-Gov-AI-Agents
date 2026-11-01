import { api } from "../js/api.js";
import { agentColor } from "../js/agents.js";

export async function renderHome(container) {
  container.innerHTML = `
    <section class="hero">
      <h1>SYNORA</h1>
      <p>Multi-agent AI for auditing algorithmic bias in government systems.</p>
      <a class="btn" href="#/chat">Free Chat</a>
    </section>
    <div class="chips" id="chips"></div>
    <h2>Scenarios</h2>
    <p id="status">Loading...</p>
    <div class="cards" id="cards"></div>`;

  const status = container.querySelector("#status");
  const cards = container.querySelector("#cards");
  const chips = container.querySelector("#chips");

  try {
    const [agents, scenarios] = await Promise.all([
      api("/agents"),
      api("/scenarios"),
    ]);
    status.remove();

    for (const a of agents) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.style.setProperty("--agent", agentColor(a.slug));
      chip.innerHTML = "<i></i><b></b>";
      chip.querySelector("b").textContent = a.name;
      chips.appendChild(chip);
    }

    for (const s of scenarios.filter((x) => x.slug !== "adhoc-chat")) {
      cards.appendChild(scenarioCard(s));
    }
  } catch (err) {
    status.textContent = "Could not load data: " + err.message;
  }
}

function scenarioCard(s) {
  const card = document.createElement("article");
  card.className = "card";
  card.style.setProperty("--agent", "#0d9488");
  card.innerHTML = `
    <h2></h2>
    <p class="mandate" dir="auto"></p>
    <button class="btn primary" type="button">Start Simulation</button>
    <p class="error" id="err"></p>`;
  card.querySelector("h2").textContent = s.title;
  card.querySelector(".mandate").textContent = s.description;

  const button = card.querySelector("button");
  const error = card.querySelector(".error");

  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Starting...";
    error.textContent = "";
    try {
      const session = await api("/sessions", {
        method: "POST",
        body: JSON.stringify({ scenario_id: s.id }),
      });
      await api(`/sessions/${session.id}/start`, { method: "POST" });
      location.hash = `#/session/${session.id}`;
    } catch (err) {
      button.disabled = false;
      button.textContent = "Start Simulation";
      error.textContent = "Could not start: " + err.message;
    }
  });
  return card;
}