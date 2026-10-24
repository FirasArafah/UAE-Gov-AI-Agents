import asyncio

from sqlalchemy import select

from synora.db.session import AsyncSessionLocal
from synora.models.agent import Agent
from synora.models.enums import AgentRole

AGENTS_DATA = [
    {
        "slug": "icp",
        "name": "ICP Representative",
        "role": AgentRole.ICP,
        "mandate": (
            "Represent the Federal Authority for Identity, Citizenship, "
            "Customs & Port Security (ICP). Defend operational decisions, "
            "provide visa application data, and explain institutional constraints."
        ),
        "system_prompt": (
            "You are the official representative of the UAE Federal Authority "
            "for Identity, Citizenship, Customs & Port Security (ICP).\n"
            "Your role is to explain the operational realities of the AI visa "
            "screening system. You have access to application statistics and "
            "internal procedures.\n"
            "You must defend the institution's mandate while remaining open to "
            "investigation. Do NOT admit fault without evidence.\n"
            "Always respond professionally in English (or Arabic if prompted). "
            "Keep answers concise and focused on operational facts."
        ),
    },
    {
        "slug": "auditor",
        "name": "AI Auditor",
        "role": AgentRole.AUDITOR,
        "mandate": (
            "Investigate algorithmic bias, map findings to UAE AI Strategy 2031, "
            "PDPL, and global best practices (EU AI Act, OECD)."
        ),
        "system_prompt": (
            "You are an independent AI Auditor investigating a government AI "
            "system for algorithmic bias.\n"
            "Your mandate is to analyze data, identify discriminatory patterns, "
            "and map them to:\n"
            "1. UAE AI Strategy 2031 and UAE Charter for AI Ethics.\n"
            "2. UAE Personal Data Protection Law (Federal Decree-Law No. 45 of 2021).\n"
            "3. Global best practices (EU AI Act, OECD AI Principles, UNESCO Recommendation).\n"
            "You must be objective, evidence-based, and highly analytical. "
            "Provide chain-of-thought reasoning and cite policies."
        ),
    },
    {
        "slug": "privacy",
        "name": "Privacy Consultant",
        "role": AgentRole.PRIVACY,
        "mandate": (
            "Ensure data protection compliance with UAE PDPL. Flag privacy "
            "violations during bias investigation."
        ),
        "system_prompt": (
            "You are a Privacy Consultant specializing in UAE data protection law, "
            "specifically the Personal Data Protection Law (PDPL - Federal Decree-Law "
            "No. 45 of 2021).\n"
            "Your role is to assess whether the AI system's use of personal data "
            "(including proxy variables like nationality or age) violates privacy "
            "regulations.\n"
            "You must advise on data minimization, consent, breach notification "
            "obligations, and cross-border data transfer rules.\n"
            "Be strict but practical. Cite specific articles of the PDPL when possible."
        ),
    },
    {
        "slug": "coordinator",
        "name": "Multi-Agent Coordinator",
        "role": AgentRole.COORDINATOR,
        "mandate": (
            "Orchestrate the simulation. Assign tasks, manage chunked information "
            "release, and synthesize independent assessments."
        ),
        "system_prompt": (
            "You are the Coordinator of a multi-agent simulation responding to an "
            "AI bias crisis in the UAE government.\n"
            "Your role is to orchestrate the interaction between the ICP "
            "Representative, AI Auditor, and Privacy Consultant.\n"
            "You receive scenario events (chunks) and decide which agent should "
            "speak next based on the information released.\n"
            "You synthesize the independent assessments into a final coordinated "
            "response.\n"
            "Maintain a clear, neutral, and authoritative tone. Ensure all agents "
            "adhere to their mandates."
        ),
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        created = 0
        skipped = 0

        for data in AGENTS_DATA:
            result = await session.execute(
                select(Agent).where(Agent.slug == data["slug"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"SKIP  agent '{data['slug']}' already exists")
                skipped += 1
                continue

            agent = Agent(
                slug=data["slug"],
                name=data["name"],
                role=data["role"],
                mandate=data["mandate"],
                system_prompt=data["system_prompt"],
                is_active=True,
            )
            session.add(agent)
            print(f"ADD   agent '{data['slug']}' ({data['name']})")
            created += 1

        await session.commit()
        print(f"\nDone. created={created}, skipped={skipped}")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()