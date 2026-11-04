import { addStrings, t } from "./i18n.js";

export const AGENTS = {
  icp: { short: "ICP", color: "#2563eb" },
  auditor: { short: "AU", color: "#ea580c" },
  privacy: { short: "PR", color: "#7c3aed" },
  coordinator: { short: "CO", color: "#0f766e" },
};

addStrings({
  en: {
    "agent.icp.name": "ICP Representative",
    "agent.icp.role": "System operator",
    "agent.auditor.name": "AI Auditor",
    "agent.auditor.role": "Bias and accountability",
    "agent.privacy.name": "Privacy Consultant",
    "agent.privacy.role": "Data protection (PDPL)",
    "agent.coordinator.name": "Coordinator",
    "agent.coordinator.role": "Final decision and escalation",
  },
  ar: {
    "agent.icp.name": "ممثل الهيئة الاتحادية للهوية والجنسية",
    "agent.icp.role": "الجهة المشغّلة للنظام",
    "agent.auditor.name": "مدقق الذكاء الاصطناعي",
    "agent.auditor.role": "التحيّز والمساءلة",
    "agent.privacy.name": "مستشار الخصوصية",
    "agent.privacy.role": "حماية البيانات الشخصية",
    "agent.coordinator.name": "المنسّق",
    "agent.coordinator.role": "القرار النهائي والتصعيد",
  },
});

export function agentColor(slug) {
  return AGENTS[slug]?.color ?? "#6b7280";
}

/** The agent's name in the interface language; the stored name is the fallback. */
export function agentName(slug, fallback) {
  return AGENTS[slug] ? t(`agent.${slug}.name`) : fallback || slug;
}

export function agentRole(slug, fallback) {
  return AGENTS[slug] ? t(`agent.${slug}.role`) : fallback || "";
}

export function agentInitials(slug, name) {
  if (AGENTS[slug]) return AGENTS[slug].short;
  return (name || slug || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}
