export const AGENTS = {
  icp: { name: "ICP Representative", short: "ICP", color: "#2563eb", mandate: "Operator of the screening system" },
  auditor: { name: "AI Auditor", short: "AU", color: "#ea580c", mandate: "Bias and model accountability" },
  privacy: { name: "Privacy Consultant", short: "PR", color: "#7c3aed", mandate: "Data protection (PDPL)" },
  coordinator: { name: "Coordinator", short: "CO", color: "#0f766e", mandate: "Synthesis and escalation" },
};

export function agentColor(slug) {
  return AGENTS[slug]?.color ?? "#6b7280";
}

export function agentName(slug, fallback) {
  return fallback || AGENTS[slug]?.name || slug;
}

export function agentInitials(slug, name) {
  if (AGENTS[slug]) return AGENTS[slug].short;
  return (name || slug || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}
