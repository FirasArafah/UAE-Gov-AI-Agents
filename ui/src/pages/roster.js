import { api } from "../js/api.js";
import { agentColor } from "../js/agents.js";

export async function renderRoster(container) {
  container.innerHTML =
    "<h1>Agents</h1><p id='status'>Loading...</p><div class='cards' id='cards'></div>";
  const status = container.querySelector("#status");
  const cards = container.querySelector("#cards");

  try {
    const agents = await api("/agents");
    status.remove();

    for (const a of agents) {
      const card = document.createElement("article");
      card.className = "card";
      card.style.setProperty("--agent", agentColor(a.slug));
      card.innerHTML = `
        <div class="avatar"></div>
        <h2></h2>
        <span class="role"></span>
        <p class="mandate" dir="auto"></p>`;
      card.querySelector(".avatar").textContent = a.name.charAt(0);
      card.querySelector("h2").textContent = a.name;
      card.querySelector(".role").textContent = a.role;
      card.querySelector(".mandate").textContent = a.mandate;
      cards.appendChild(card);
    }
  } catch (err) {
    status.textContent = "Could not load agents: " + err.message;
  }
}