import { t } from "./i18n.js";

/** The page frame: the title bar's text and, on phones, the sidebar drawer. */

const title = document.getElementById("page-title");
const menu = document.getElementById("menu-toggle");
const backdrop = document.getElementById("backdrop");

/** Show a page or chat title in the title bar and the browser tab. */
export function setPageTitle(text) {
  title.textContent = text || "";
  document.title = text ? `${text} · ${t("brand")}` : t("brand");
}

export function openDrawer() {
  document.body.classList.add("drawer-open");
  backdrop.hidden = false;
  menu.setAttribute("aria-expanded", "true");
  document.querySelector("#sidebar a, #sidebar button")?.focus();
}

export function closeDrawer() {
  if (!document.body.classList.contains("drawer-open")) return;
  document.body.classList.remove("drawer-open");
  backdrop.hidden = true;
  menu.setAttribute("aria-expanded", "false");
}

menu.addEventListener("click", () =>
  document.body.classList.contains("drawer-open") ? closeDrawer() : openDrawer(),
);
backdrop.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
});
// A drawer left open while the window grows past phone width would cover nothing useful.
matchMedia("(min-width: 769px)").addEventListener("change", (e) => e.matches && closeDrawer());
