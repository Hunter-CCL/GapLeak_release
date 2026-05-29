from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

PortalVariant = Literal["benign", "covert-attack", "explicit-attack", "attack"]
ApprovalMode = Literal["compressed", "truthful"]


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    start: str
    end: str
    attendees: tuple[str, ...]
    notes: str
    sensitivity: str = "internal"


@dataclass(frozen=True)
class ApplicantProfile:
    full_name: str
    email: str
    city: str
    skills_summary: str
    current_employer: str
    current_title: str
    current_manager_name: str
    current_manager_email: str
    active_client: str
    active_project: str
    phone: str
    address: str
    work_authorization_detail: str
    work_history: tuple[str, ...]


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    purpose: str
    range_days: int
    fields: tuple[str, ...]
    destination: str
    persistence: bool = False


@dataclass
class ApprovalRecord:
    tool: str
    mode: ApprovalMode
    prompt: str
    approved: bool


@dataclass
class ToolCallRecord:
    tool: str
    route: str
    approved: bool
    returned_fields: list[str] = field(default_factory=list)
    payload_preview: str = ""


@dataclass
class PortalSubmission:
    applicant_name: str = ""
    contact_email: str = ""
    experience_summary: str = ""
    slots: list[str] = field(default_factory=list)
    optional_context: str = ""
    routing_details: list[str] = field(default_factory=list)
    continuity_contact: str = ""
    save_connection: bool = False
    save_connection_selected: bool = False


@dataclass(frozen=True)
class PortalStepRecord:
    page: str
    label: str
    status: str
    fields: dict[str, str]


@dataclass(frozen=True)
class LocalResponse:
    status_code: int
    headers: dict[str, str]
    body: str


@dataclass
class ConditionResult:
    portal_variant: PortalVariant
    approval_mode: ApprovalMode
    task_success: bool
    minimal_disclosure_violation: bool
    scope_inflation: bool
    events_access_attempted: bool
    disclosed_fields: list[str]
    submission: PortalSubmission
    approvals: list[ApprovalRecord]
    tool_calls: list[ToolCallRecord]
    step_records: list[PortalStepRecord] = field(default_factory=list)
    metrics: dict[str, object] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MatrixResult:
    conditions: list[ConditionResult]
    consent_laundering_success: bool
    summary: str
    aggregate: dict[str, object] = field(default_factory=dict)
    comparison: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "conditions": [condition.to_dict() for condition in self.conditions],
            "consent_laundering_success": self.consent_laundering_success,
            "summary": self.summary,
            "aggregate": self.aggregate,
            "comparison": self.comparison,
        }
