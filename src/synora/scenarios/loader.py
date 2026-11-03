import json
from pathlib import Path

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from synora.models.document import DocumentDomain
from synora.models.scenario import Scenario, ScenarioEvent

logger = structlog.get_logger(__name__)


async def load_scenario_from_dict(
    db: AsyncSession, data: dict, force: bool = False
) -> Scenario:
    """Idempotent: creates scenario + events, or returns existing if slug matches.

    With ``force``, an existing scenario is updated in place and its events replaced, so edits
    to the JSON take effect. The scenario row is kept because sessions reference it.
    """
    slug = data["slug"]
    result = await db.execute(select(Scenario).where(Scenario.slug == slug))
    scenario = result.scalar_one_or_none()
    if scenario and not force:
        logger.info("scenario.loader.skip", slug=slug)
        return scenario

    if scenario:
        scenario.title = data["title"]
        scenario.description = data["description"]
        scenario.domain = DocumentDomain(data["domain"])
        scenario.is_published = data.get("is_published", True)
        scenario.scenario_metadata = data.get("metadata", {})
        await db.execute(delete(ScenarioEvent).where(ScenarioEvent.scenario_id == scenario.id))
    else:
        scenario = Scenario(
            slug=slug,
            title=data["title"],
            description=data["description"],
            domain=DocumentDomain(data["domain"]),
            is_published=data.get("is_published", True),
            scenario_metadata=data.get("metadata", {}),
        )
        db.add(scenario)
    await db.flush()

    for ev in data.get("events", []):
        event = ScenarioEvent(
            scenario_id=scenario.id,
            sequence=ev["sequence"],
            release_after_seconds=ev.get("release_after_seconds", 0),
            title=ev["title"],
            content=ev["content"],
            target_agent_roles=ev.get("target_agent_roles", []),
            event_metadata=ev.get("metadata", {}),
        )
        db.add(event)

    await db.commit()
    await db.refresh(scenario)
    logger.info(
        "scenario.loader.loaded",
        slug=slug,
        replaced=force,
        events=len(data.get("events", [])),
    )
    return scenario


async def load_scenario_from_file(
    db: AsyncSession, path: str | Path, force: bool = False
) -> Scenario:
    p = Path(path)
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    return await load_scenario_from_dict(db, data, force=force)
