from enum import StrEnum

EMBEDDING_DIM = 1024


class AgentRole(StrEnum):
    ICP = "icp"
    AUDITOR = "auditor"
    PRIVACY = "privacy"
    COORDINATOR = "coordinator"
    DOMAIN_APP = "domain_app"
    REGULATOR = "regulator"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class SimulationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ScenarioEventStatus(StrEnum):
    PENDING = "pending"
    RELEASED = "released"
    ACKNOWLEDGED = "acknowledged"


class AuditAction(StrEnum):
    RETRIEVAL = "retrieval"
    REASONING = "reasoning"
    DECISION = "decision"
    POLICY_REFERENCE = "policy_reference"
    HANDOFF = "handoff"
    ESCALATION = "escalation"
    ERROR = "error"


class DocumentDomain(StrEnum):
    GOVERNMENT_SERVICES = "government_services"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    TELECOM = "telecom"
    CROSS_DOMAIN = "cross_domain"


class DocumentType(StrEnum):
    LAW = "law"
    REGULATION = "regulation"
    STRATEGY = "strategy"
    GUIDELINE = "guideline"
    STANDARD = "standard"
    REPORT = "report"
    USE_CASE = "use_case"
    OTHER = "other"


class GapType(StrEnum):
    POLICY = "policy"
    LEGAL = "legal"
    STANDARDS = "standards"
    IMPLEMENTATION = "implementation"
    COORDINATION = "coordination"