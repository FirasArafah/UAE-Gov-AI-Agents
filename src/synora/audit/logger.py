from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from synora.models.audit import AuditLog
from synora.models.enums import AuditAction

logger = structlog.get_logger(__name__)


class AuditLogger:
    """Persists agent reasoning, decisions, and citations to audit_logs.

    Every call flushes (but does not commit) so multiple entries can be
    batched by the caller within a single transaction.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log_reasoning(
        self,
        session_id: UUID,
        agent_id: UUID,
        message_id: UUID | None,
        reasoning: str,
        policy_references: list[dict] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            session_id=session_id,
            agent_id=agent_id,
            message_id=message_id,
            action=AuditAction.REASONING,
            reasoning=reasoning,
            policy_references=policy_references or [],
            source_attributions=[],
        )
        self.db.add(entry)
        await self.db.flush()
        logger.info(
            "audit.reasoning",
            session=str(session_id),
            agent=str(agent_id),
            chars=len(reasoning),
        )
        return entry

    async def log_decision(
        self,
        session_id: UUID,
        agent_id: UUID,
        message_id: UUID | None,
        reasoning: str,
        confidence: float | None = None,
        source_attributions: list[dict] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            session_id=session_id,
            agent_id=agent_id,
            message_id=message_id,
            action=AuditAction.DECISION,
            reasoning=reasoning,
            confidence=confidence,
            source_attributions=source_attributions or [],
            policy_references=[],
        )
        self.db.add(entry)
        await self.db.flush()
        logger.info(
            "audit.decision",
            session=str(session_id),
            agent=str(agent_id),
            chars=len(reasoning),
        )
        return entry

    async def log_retrieval(
        self,
        session_id: UUID,
        agent_id: UUID,
        query: str,
        references: list[dict],
    ) -> AuditLog:
        entry = AuditLog(
            session_id=session_id,
            agent_id=agent_id,
            action=AuditAction.RETRIEVAL,
            reasoning=f"Retrieved {len(references)} chunks for query: {query[:100]}",
            policy_references=references,
            audit_metadata={"query": query},
        )
        self.db.add(entry)
        await self.db.flush()
        logger.info(
            "audit.retrieval",
            session=str(session_id),
            agent=str(agent_id),
            refs=len(references),
        )
        return entry
