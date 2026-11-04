import { api } from "../js/api.js";
import { AGENTS, agentColor, agentInitials, agentName, agentRole } from "../js/agents.js";
import { addStrings, t } from "../js/i18n.js";
import { h } from "../js/render.js";

const SPECIALISTS = ["icp", "auditor", "privacy"];

addStrings({
  en: {
    "agents.title": "Agents",
    "agents.subtitle": "Four agents, each speaking for a different institution and answering from the law it is responsible for.",
    "agents.flow.title": "How a team answer is made",
    "agents.flow.independent": "Assess independently",
    "agents.flow.coordinator": "Reconciles the assessments",
    "agents.flow.answer": "One final answer",
    "agents.mandate": "Mandate",
    "agents.sources": "Primary sources",
    "agents.ask": "Ask this agent",
    "agents.mandate.icp": "Speaks for the Federal Authority for Identity, Citizenship, Customs & Port Security, the operator of the screening system: defends its legal and security mandate, explains operational constraints and proposes remedies it can implement.",
    "agents.mandate.auditor": "Independent technical auditor: tests the model for bias and accountability gaps and measures them against national AI principles and international standards.",
    "agents.mandate.privacy": "Data protection adviser: assesses the processing of personal data under the Personal Data Protection Law, including automated decisions, proxy variables and data subject rights.",
    "agents.mandate.coordinator": "Chairs the response: reconciles the independent assessments into one decision, names the authority responsible for each action and escalates what needs a human decision.",
    "agents.sources.icp": "Entry and residence law and its executive regulations",
    "agents.sources.auditor": "AI strategy, charter and ethics guidelines; ITU, OECD, UNESCO, EU AI Act",
    "agents.sources.privacy": "Personal Data Protection Law (PDPL)",
    "agents.sources.coordinator": "The assessments of the other three agents",
  },
  ar: {
    "agents.title": "الوكلاء",
    "agents.subtitle": "أربعة وكلاء، يمثّل كلٌّ منهم جهة مختلفة ويجيب استناداً إلى التشريع الذي تختص به.",
    "agents.flow.title": "كيف تُبنى إجابة الفريق",
    "agents.flow.independent": "تقييمات مستقلة",
    "agents.flow.coordinator": "يوفّق بين التقييمات",
    "agents.flow.answer": "إجابة نهائية واحدة",
    "agents.mandate": "الاختصاص",
    "agents.sources": "المصادر الأساسية",
    "agents.ask": "اسأل هذا الوكيل",
    "agents.mandate.icp": "يمثّل الهيئة الاتحادية للهوية والجنسية والجمارك وأمن المنافذ، الجهة المشغّلة لنظام الفرز: يدافع عن اختصاصها القانوني والأمني، ويوضّح القيود التشغيلية، ويقترح حلولاً قابلة للتطبيق.",
    "agents.mandate.auditor": "مدقق تقني مستقل: يختبر النموذج بحثاً عن التحيّز وثغرات المساءلة، ويقيسها بمبادئ الذكاء الاصطناعي الوطنية والمعايير الدولية.",
    "agents.mandate.privacy": "مستشار حماية البيانات: يقيّم معالجة البيانات الشخصية وفق قانون حماية البيانات الشخصية، بما في ذلك القرارات الآلية والمتغيرات البديلة وحقوق صاحب البيانات.",
    "agents.mandate.coordinator": "يرأس الاستجابة: يوفّق بين التقييمات المستقلة في قرار واحد، ويحدّد الجهة المسؤولة عن كل إجراء، ويصعّد ما يتطلب قراراً بشرياً.",
    "agents.sources.icp": "قانون دخول وإقامة الأجانب ولائحته التنفيذية",
    "agents.sources.auditor": "استراتيجية الذكاء الاصطناعي والميثاق وإرشادات الأخلاقيات؛ ITU وOECD وUNESCO وقانون الذكاء الاصطناعي الأوروبي",
    "agents.sources.privacy": "قانون حماية البيانات الشخصية",
    "agents.sources.coordinator": "تقييمات الوكلاء الثلاثة الآخرين",
  },
});

function avatar(slug, size = "") {
  return h("span", { class: `avatar ${size}`.trim(), "--agent": agentColor(slug), text: agentInitials(slug) });
}

export async function renderRoster(container) {
  const cards = h("div", { class: "agent-grid" });
  container.append(
    h("header", { class: "page-head" },
      h("div", {}, h("h1", { text: t("agents.title") }), h("p", { text: t("agents.subtitle") })),
    ),
    h("section", { class: "panel flow", "aria-label": t("agents.flow.title") },
      h("h2", { text: t("agents.flow.title") }),
      h("div", { class: "flow-row" },
        h("div", { class: "flow-step" },
          h("div", { class: "flow-avatars" }, SPECIALISTS.map((s) => avatar(s))),
          h("span", { text: t("agents.flow.independent") }),
        ),
        h("span", { class: "flow-arrow", "aria-hidden": "true" }),
        h("div", { class: "flow-step" },
          h("div", { class: "flow-avatars" }, avatar("coordinator")),
          h("span", { text: t("agents.flow.coordinator") }),
        ),
        h("span", { class: "flow-arrow", "aria-hidden": "true" }),
        h("div", { class: "flow-step final" },
          h("div", { class: "flow-avatars" }, h("span", { class: "flow-check", "aria-hidden": "true", text: "✓" })),
          h("span", { text: t("agents.flow.answer") }),
        ),
      ),
    ),
    cards,
  );

  let agents = [];
  try {
    agents = await api("/agents");
  } catch (err) {
    cards.replaceChildren(h("p", { class: "error", text: t("common.loadFailed", { error: err.message }) }));
    return;
  }
  const order = Object.keys(AGENTS);
  agents.sort((a, b) => order.indexOf(a.slug) - order.indexOf(b.slug));
  for (const a of agents) {
    const known = Boolean(AGENTS[a.slug]);
    cards.append(
      h("article", { class: "agent-card", "--agent": agentColor(a.slug) },
        h("div", { class: "agent-head" },
          avatar(a.slug, "lg"),
          h("div", {}, h("h3", { text: agentName(a.slug, a.name) }), h("small", { text: agentRole(a.slug, a.role) })),
        ),
        h("div", { class: "agent-block" },
          h("h4", { text: t("agents.mandate") }),
          h("p", { text: known ? t(`agents.mandate.${a.slug}`) : a.mandate }),
        ),
        known
          ? h("div", { class: "agent-block" },
              h("h4", { text: t("agents.sources") }),
              h("p", { class: "muted", text: t(`agents.sources.${a.slug}`) }),
            )
          : null,
        h("div", { class: "card-actions" }, h("a", { class: "btn sm", href: `/ask/${a.slug}`, text: t("agents.ask") })),
      ),
    );
  }
}
