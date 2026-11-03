"""Policy gap extraction: turns a session's agent assessments into structured gap records.

The specialist agents surface gaps in prose. This step reads their assessments, retrieves
international reference material (ITU, OECD, UNESCO, EU AI Act) from the knowledge base and
asks the model for a structured list of domain-level gaps, each mapped to the global best
practice that addresses it. Only references that were actually retrieved can be cited.
"""

import json
from dataclasses import dataclass

import structlog

from synora.agents.llm import LLMClient
from synora.agents.types import Retriever
from synora.models.enums import DocumentDomain, GapType

logger = structlog.get_logger(__name__)

# Themes the Golden Gate assessments revolve around. Each one pulls international practice
# from the knowledge base, so the gap report can name a concrete global example.
GLOBAL_PRACTICE_QUERIES = (
    "human oversight of high-risk AI systems used in public services",
    "non-discrimination, bias testing and fairness of automated decisions",
    "authority to suspend, withdraw or recall an AI system that causes harm",
    "transparency, explanation and right to contest automated decisions",
    "independent oversight body and accountability for public sector AI",
    "data governance and quality of training data for machine learning",
)
INTERNATIONAL_DOMAINS = [DocumentDomain.CROSS_DOMAIN.value]
REFERENCES_PER_QUERY = 2
ASSESSMENT_EXCERPT_CHARS = 700
MAX_ASSESSMENTS = 10
SEVERITIES = ("low", "medium", "high", "critical")

SYSTEM_PROMPT = """You are a policy analyst preparing a gap report for a multi-agent AI governance \
exercise. Government agents assessed an incident in which an AI visa-screening system \
disproportionately rejected applicants of one nationality.

Identify the domain-level gaps their assessments reveal: unclear responsibilities, missing \
standards, technology or legislative gaps, coordination problems, and conflicts between \
objectives. Focus on the domain (government AI in public services), not on recommendations \
for one specific country.

For each gap, name the global best practice that addresses it, using ONLY the numbered \
INTERNATIONAL REFERENCES provided, and list the numbers you relied on in reference_ids. If no \
reference addresses a gap, leave reference_ids empty and say so in global_best_practice.

Return JSON only, in this exact shape:
{"gaps": [{
  "title": "short name of the gap",
  "gap_type": "policy | legal | standards | implementation | coordination",
  "description": "what is missing or conflicting, and why it matters (2-4 sentences)",
  "evidence": "which agent assessment(s) surfaced it",
  "affected_domain": "government_services | data_protection | ai_governance | cross_domain",
  "severity": "low | medium | high | critical",
  "global_best_practice": "how the referenced international instruments address it",
  "reference_ids": [1, 2]
}]}
Report between 3 and 6 gaps, most severe first."""


@dataclass
class ExtractedGap:
    gap_type: str
    description: str
    affected_domain: str
    severity: str
    global_best_practice: str | None
    global_references: list[dict]


def _excerpt(text: str) -> str:
    body = text.split("\n\n---\n", 1)[0]
    english = body.split("English version:", 1)
    if len(english) == 2 and english[1].strip():
        body = english[1]
    body = body.strip()
    if len(body) > ASSESSMENT_EXCERPT_CHARS:
        body = body[:ASSESSMENT_EXCERPT_CHARS].rstrip() + " ..."
    return body


def _choice(value: object, allowed: list[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


class GapAnalyst:
    def __init__(self, llm: LLMClient, retriever: Retriever | None) -> None:
        self.llm = llm
        self.retriever = retriever

    async def _global_references(self) -> list[dict]:
        if not self.retriever:
            return []
        seen: dict[str, dict] = {}
        for query in GLOBAL_PRACTICE_QUERIES:
            try:
                hits = await self.retriever.search(
                    query, top_k=REFERENCES_PER_QUERY, domains=INTERNATIONAL_DOMAINS
                )
            except Exception as exc:
                logger.warning("gaps.retrieval_failed", query=query, error=str(exc))
                continue
            for hit in hits:
                seen.setdefault(hit["chunk_id"], hit)
        return list(seen.values())

    async def extract(self, assessments: list[dict]) -> tuple[list[ExtractedGap], list[dict]]:
        """Return the gaps found in ``assessments`` ({agent_name, event, content}) and the
        international references that were offered to the model."""
        references = await self._global_references()
        recent = assessments[-MAX_ASSESSMENTS:]

        assessment_lines = [
            f"[{a['agent_name']} — event {a['event']}]\n{_excerpt(a['content'])}" for a in recent
        ]
        reference_lines = [
            f"[{i}] {r.get('title')}"
            + (f" | {r['section']}" if r.get("section") else "")
            + f"\n{(r.get('content') or '')[:600]}"
            for i, r in enumerate(references, start=1)
        ]
        user = (
            "AGENT ASSESSMENTS:\n\n"
            + "\n\n".join(assessment_lines)
            + "\n\nINTERNATIONAL REFERENCES:\n\n"
            + ("\n\n".join(reference_lines) or "(none retrieved)")
        )

        raw = await self.llm.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            num_predict=2048,
            json_mode=True,
        )
        return self._parse(raw, references), references

    def _parse(self, raw: str, references: list[dict]) -> list[ExtractedGap]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("gaps.invalid_json", raw=raw[:300])
            return []
        items = data.get("gaps", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []

        gap_types = [g.value for g in GapType]
        domains = [d.value for d in DocumentDomain]
        gaps: list[ExtractedGap] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("description"):
                continue
            cited = []
            for ref_id in item.get("reference_ids") or []:
                # The model may only cite references it was shown; anything else is dropped.
                if isinstance(ref_id, int) and 1 <= ref_id <= len(references):
                    ref = references[ref_id - 1]
                    cited.append(
                        {
                            "title": ref.get("title"),
                            "section": ref.get("section"),
                            "page": ref.get("page"),
                            "chunk_id": ref.get("chunk_id"),
                            "excerpt": (ref.get("content") or "")[:300],
                        }
                    )
            title = str(item.get("title") or "").strip()
            description = str(item["description"]).strip()
            evidence = str(item.get("evidence") or "").strip()
            gaps.append(
                ExtractedGap(
                    gap_type=_choice(item.get("gap_type"), gap_types, GapType.POLICY.value),
                    description=(f"{title}: " if title else "")
                    + description
                    + (f"\nEvidence: {evidence}" if evidence else ""),
                    affected_domain=_choice(
                        item.get("affected_domain"),
                        domains,
                        DocumentDomain.GOVERNMENT_SERVICES.value,
                    ),
                    severity=_choice(item.get("severity"), list(SEVERITIES), "medium"),
                    global_best_practice=str(item.get("global_best_practice") or "").strip()
                    or None,
                    global_references=cited,
                )
            )
        return gaps
