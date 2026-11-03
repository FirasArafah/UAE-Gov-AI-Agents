export const AGENTS = {
  icp: { name: "ICP Representative", color: "#2563eb" },
  auditor: { name: "AI Auditor", color: "#ea580c" },
  privacy: { name: "Privacy Consultant", color: "#7c3aed" },
  coordinator: { name: "Coordinator", color: "#16a34a" },
};

export function agentColor(slug) {
  return AGENTS[slug]?.color ?? "#6b7280";
}