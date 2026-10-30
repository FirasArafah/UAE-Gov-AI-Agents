import "./style.css";
import { route, startRouter } from "./js/router.js";
import { renderHome } from "./pages/home.js";

const saved = localStorage.getItem("theme");
if (saved) document.documentElement.dataset.theme = saved;

document.getElementById("theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
});

route("/", renderHome);
startRouter(document.getElementById("app"));