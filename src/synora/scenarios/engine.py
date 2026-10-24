from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from synora.models.enums import SimulationStatus
from synora.models.scenario import Scenario, ScenarioEvent
from synora.models.simulation import SimulationSession

logger = structlog.get_logger(__name__)


class ScenarioEngine:
    """Releases scenario events progressively to the session's agents."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def start_session(self, session_id: UUID) -> SimulationSession:
        session = await self.db.get(SimulationSession, session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        session.status = SimulationStatus.RUNNING
        session.started_at = datetime.now(timezone.utc)
        session.current_sequence = 0
        await self.db.commit()
        await self.db.refresh(session)
        logger.info("scenario.engine.started", session=str(session_id))
        return session

    async def next_event(self, session_id: UUID) -> ScenarioEvent | None:
        """Return the next event to release, or None if scenario exhausted."""
        session = await self.db.get(SimulationSession, session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")

        result = await self.db.execute(
            select(ScenarioEvent)
            .where(
                ScenarioEvent.scenario_id == session.scenario_id,
                ScenarioEvent.sequence > session.current_sequence,
            )
            .order_by(ScenarioEvent.sequence)
            .limit(1)
        )
        event = result.scalar_one_or_none()

        if event is None:
            session.status = SimulationStatus.COMPLETED
            session.ended_at = datetime.now(timezone.utc)
            await self.db.commit()
            logger.info("scenario.engine.completed", session=str(session_id))
            return None

        session.current_sequence = event.sequence

        # Auto-complete if this was the last event
        last_check = await self.db.execute(
            select(func.count())
            .select_from(ScenarioEvent)
            .where(
                ScenarioEvent.scenario_id == session.scenario_id,
                ScenarioEvent.sequence > event.sequence,
            )
        )
        remaining = last_check.scalar() or 0
        if remaining == 0:
            session.status = SimulationStatus.COMPLETED
            session.ended_at = datetime.now(timezone.utc)
            logger.info(
                "scenario.engine.completed_on_last_event",
                session=str(session_id),
            )

        await self.db.commit()
        await self.db.refresh(event)
        logger.info(
            "scenario.engine.event_released",
            session=str(session_id),
            sequence=event.sequence,
            targets=event.target_agent_roles,
        )
        return event

    async def timeline(self, session_id: UUID) -> dict:
        """Full scenario timeline + session progress."""
        session = await self.db.get(SimulationSession, session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")

        scenario = await self.db.get(Scenario, session.scenario_id)
        if scenario is None:
            raise ValueError(f"scenario not found: {session.scenario_id}")

        result = await self.db.execute(
            select(ScenarioEvent)
            .where(ScenarioEvent.scenario_id == scenario.id)
            .order_by(ScenarioEvent.sequence)
        )
        events = result.scalars().all()

        return {
            "session_id": str(session_id),
            "scenario_slug": scenario.slug,
            "status": session.status,
            "current_sequence": session.current_sequence,
            "total_events": len(events),
            "events": [
                {
                    "sequence": e.sequence,
                    "title": e.title,
                    "target_agent_roles": e.target_agent_roles,
                    "released": e.sequence <= session.current_sequence,
                }
                for e in events
            ],
        }
