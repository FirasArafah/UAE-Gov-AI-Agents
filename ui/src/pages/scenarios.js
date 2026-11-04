import { api } from "../js/api.js";
import { AGENTS, agentColor, agentInitials, agentName } from "../js/agents.js";
import { addStrings, language, num, t } from "../js/i18n.js";
import { h, textDir } from "../js/render.js";
import { navigate } from "../js/router.js";

addStrings({
  en: {
    "sim.title": "Simulations",
    "sim.subtitle": "Staged incidents released one event at a time. Each agency assesses what it receives, and the Coordinator reconciles them.",
    "sim.scenarios": "Scenarios",
    "sim.start": "Start simulation",
    "sim.starting": "Starting…",
    "sim.startFailed": "The simulation could not start: {error}",
    "sim.controversy": "Includes a contested decision",
    "sim.runs": "Previous runs",
    "sim.runs.none": "No simulation has been run yet.",
    "sim.run.progress": "Reached event {n}",
    "sim.run.messages": "{n} messages",
    "status.pending": "Not started",
    "status.running": "In progress",
    "status.completed": "Completed",
    "status.paused": "Paused",
    "status.failed": "Failed",
  },
  ar: {
    "sim.title": "المحاكاة",
    "sim.subtitle": "حوادث مُعدّة تُكشف أحداثها تباعاً. تقيّم كل جهة ما يصلها، ويوفّق المنسّق بين التقييمات.",
    "sim.scenarios": "السيناريوهات",
    "sim.start": "بدء المحاكاة",
    "sim.starting": "جارٍ البدء…",
    "sim.startFailed": "تعذّر بدء المحاكاة: {error}",
    "sim.controversy": "يتضمن قراراً متنازعاً عليه",
    "sim.runs": "عمليات التشغيل السابقة",
    "sim.runs.none": "لم تُشغَّل أي محاكاة بعد.",
    "sim.run.progress": "وصلت إلى الحدث {n}",
    "sim.run.messages": "{n} رسالة",
    "status.pending": "لم تبدأ",
    "status.running": "قيد التنفيذ",
    "status.completed": "مكتملة",
    "status.paused": "متوقفة مؤقتاً",
    "status.failed": "فشلت",
  },
});

export const statusLabel = (status) => t(`status.${status}`);

/** Scenario text in the interface language, from the Arabic copy in its metadata. */
export function scenarioText(scenario) {
  const meta = scenario.scenario_metadata || {};
  const ar = language() === "ar";
  return {
    title: (ar && meta.title_ar) || scenario.title,
    description: (ar && meta.description_ar) || scenario.description,
  };
}

export async function renderScenarios(container) {
  const cards = h("div", { class: "scenario-grid" }, h("div", { class: "skeleton", style: { height: "180px" } }));
  const runs = h("div", { class: "run-list" });
  container.append(
    h("header", { class: "page-head" },
      h("div", {}, h("h1", { text: t("sim.title") }), h("p", { text: t("sim.subtitle") })),
    ),
    h("section", { class: "section" }, h("h2", { text: t("sim.scenarios") }), cards),
    h("section", { class: "section" }, h("h2", { text: t("sim.runs") }), runs),
  );

  try {
    const [scenarios, sessions] = await Promise.all([api("/scenarios"), api("/sessions?limit=50")]);
    const titles = Object.fromEntries(scenarios.map((s) => [s.id, scenarioText(s).title]));
    cards.replaceChildren(...scenarios.map(scenarioCard));

    // Runs that never released an event hold nothing to review.
    const used = sessions.filter((s) => s.message_count > 0);
    runs.replaceChildren(
      ...(used.length
        ? used.map((s) => runRow(s, titles[s.scenario_id] || s.scenario_title))
        : [h("div", { class: "empty", text: t("sim.runs.none") })]),
    );
  } catch (err) {
    cards.replaceChildren(h("p", { class: "error", text: t("common.loadFailed", { error: err.message }) }));
  }
}

function scenarioCard(s) {
  const { title, description } = scenarioText(s);
  const meta = s.scenario_metadata || {};
  const error = h("p", { class: "error" });
  const button = h("button", { class: "btn primary", type: "button", text: t("sim.start") });
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = t("sim.starting");
    error.textContent = "";
    try {
      const session = await api("/sessions", { method: "POST", body: JSON.stringify({ scenario_id: s.id }) });
      await api(`/sessions/${session.id}/start`, { method: "POST" });
      navigate(`/simulation/${session.id}`);
    } catch (err) {
      button.disabled = false;
      button.textContent = t("sim.start");
      error.textContent = t("sim.startFailed", { error: err.message });
    }
  });
  return h("article", { class: "scenario-card" },
    h("div", { class: "tags" },
      meta.includes_controversy ? h("span", { class: "tag warn", text: t("sim.controversy") }) : null,
    ),
    h("h3", { dir: textDir(title), text: title }),
    h("p", { dir: textDir(description), text: description }),
    h("div", { class: "card-actions" },
      button,
      h("span", { class: "avatar-stack" },
        Object.keys(AGENTS).map((slug) => h("span", { class: "avatar sm", "--agent": agentColor(slug), title: agentName(slug), text: agentInitials(slug) })),
      ),
    ),
    error,
  );
}

function runRow(s, title) {
  const date = new Date(s.created_at).toLocaleString(language() === "ar" ? "ar-AE-u-nu-latn" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return h("a", { class: "run-row", href: `/simulation/${s.id}` },
    h("span", { class: "status-pill", "data-status": s.status, text: statusLabel(s.status) }),
    h("span", { class: "run-main" },
      h("b", { dir: textDir(title), text: title }),
      h("small", { text: `${t("sim.run.progress", { n: num(s.current_sequence) })} · ${t("sim.run.messages", { n: num(s.message_count) })}` }),
    ),
    h("small", { class: "run-date", text: date }),
  );
}
