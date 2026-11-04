import { AGENTS, agentColor, agentInitials, agentName, agentRole } from "./agents.js";
import { addStrings, t } from "./i18n.js";
import { h } from "./render.js";

addStrings({
  en: {
    "picker.label": "Who answers",
    "picker.team": "Team",
    "picker.teamHint": "Three specialists assess, the Coordinator writes the final answer",
  },
  ar: {
    "picker.label": "من يجيب",
    "picker.team": "الفريق",
    "picker.teamHint": "يقيّم ثلاثة متخصصين ثم يكتب المنسّق الإجابة النهائية",
  },
});

const CHEVRON = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M7 10l5 5 5-5z"/></svg>';
const CHECK = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>';

const badge = (slug) =>
  h("span", { class: "picker-badge", "--agent": agentColor(slug), text: agentInitials(slug) });

/**
 * Chooses who answers: the team or one agent. Works like a select element: read and set
 * `value` ("team" or an agent slug) and `disabled`; the menu opens upwards from the composer.
 */
export function createAgentPicker(initial = "team") {
  const options = [
    { value: "team", title: t("picker.team"), hint: t("picker.teamHint"), badges: Object.keys(AGENTS) },
    ...Object.keys(AGENTS).map((slug) => ({ value: slug, title: agentName(slug), hint: agentRole(slug), badges: [slug] })),
  ];
  let value = initial;
  let open = false;

  const current = h("span", { class: "picker-current" });
  const button = h("button", {
    class: "picker-button", type: "button", "aria-haspopup": "listbox", "aria-expanded": "false",
    "aria-label": t("picker.label"), title: t("picker.label"),
  }, current, h("span", { class: "picker-chevron", html: CHEVRON }));
  const list = h("ul", { class: "picker-menu", role: "listbox", "aria-label": t("picker.label"), hidden: true });
  const el = h("div", { class: "picker" }, button, list);

  function draw() {
    const option = options.find((o) => o.value === value) || options[0];
    current.replaceChildren(
      h("span", { class: "picker-badges" }, option.badges.map(badge)),
      h("span", { class: "picker-title", text: option.title }),
    );
    list.replaceChildren(
      ...options.map((o, i) =>
        h("li", {
          class: "picker-option", role: "option", tabindex: "-1", "data-value": o.value,
          "aria-selected": String(o.value === value), id: `picker-option-${i}`,
          onclick: () => choose(o.value),
        },
          h("span", { class: "picker-badges" }, o.badges.map(badge)),
          h("span", { class: "picker-text" }, h("b", { text: o.title }), h("small", { text: o.hint })),
          h("span", { class: "picker-check", html: o.value === value ? CHECK : "" }),
        ),
      ),
    );
  }

  function setOpen(next) {
    open = next;
    list.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    if (open) (list.querySelector('[aria-selected="true"]') || list.firstChild)?.focus();
  }

  function choose(next) {
    value = next;
    draw();
    setOpen(false);
    button.focus();
  }

  button.addEventListener("click", () => setOpen(!open));
  button.addEventListener("keydown", (e) => {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
    }
  });
  list.addEventListener("keydown", (e) => {
    const items = [...list.children];
    const index = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(index + step + items.length) % items.length].focus();
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (index >= 0) choose(items[index].dataset.value);
    } else if (e.key === "Escape" || e.key === "Tab") {
      setOpen(false);
      if (e.key === "Escape") button.focus();
    }
  });
  document.addEventListener("click", (e) => {
    if (open && !el.contains(e.target)) setOpen(false);
  });

  draw();
  return {
    el,
    get value() {
      return value;
    },
    set value(next) {
      if (options.some((o) => o.value === next)) {
        value = next;
        draw();
      }
    },
    set disabled(flag) {
      button.disabled = flag;
      if (flag) setOpen(false);
    },
  };
}
