import { api } from "../js/api.js";

export async function renderHome(container) {
  container.innerHTML = "<h1>Scenarios</h1><p id='status'>Loading...</p>";
  const status = container.querySelector("#status");
  try {
    const scenarios = await api("/scenarios");
    status.textContent = scenarios.length + " scenarios loaded";
  } catch (err) {
    status.textContent = "Backend not reachable: " + err.message;
  }
}