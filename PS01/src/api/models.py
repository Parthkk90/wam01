"""
Pydantic v2 models for FastAPI endpoints.
All models follow Pydantic v2 syntax.
"""

from pydantic import BaseModel, ConfigDict
from typing import List, Dict, Any, Optional
from datetime import datetime


class SessionStartRequest(BaseModel):
    """Request to start a new session."""
    customer_id: str
    session_type: str
    agent_id: str
    consent_id: str

    model_config = ConfigDict(str_strip_whitespace=True)


class SessionStartResponse(BaseModel):
    """Response when session starts."""
    session_id: str
    status: str
    briefing: Optional[Dict[str, Any]] = None
    cbs_facts_loaded: Optional[int] = None
    error_message: Optional[str] = None
    greeting_message: str = "Welcome! How can I help you today?"
    context_summary: str = ""
    suggested_next: str = ""
    has_prior_context: bool = False

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "sess_abc123",
            "status": "ready",
            "briefing": {},
            "cbs_facts_loaded": 5,
            "greeting_message": "Hi Rajesh! I can see we've spoken before about your home loan...",
            "context_summary": "Income ₹62k, co-applicant ₹30k, land record verified.",
            "suggested_next": "We need your latest payslip to confirm revised income.",
            "has_prior_context": True
        }
    })


class SessionEndRequest(BaseModel):
    """Request to end a session."""
    session_id: str
    transcript: Optional[str] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class SessionEndResponse(BaseModel):
    """Response when session ends."""
    status: str
    facts_count: int
    compact_triggered: bool

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "completed",
            "facts_count": 5,
            "compact_triggered": True
        }
    })


class SessionAddFactRequest(BaseModel):
    """Request to add a single fact during session."""
    session_id: str
    fact_type: str
    fact_value: str
    verified: bool = False

    model_config = ConfigDict(str_strip_whitespace=True)


class SessionAddFactResponse(BaseModel):
    """Response after adding a fact."""
    fact_id: str
    wal_written: bool
    redpanda_published: bool

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "fact_id": "FACT_123",
            "wal_written": True,
            "redpanda_published": True
        }
    })


class ConsentRecordRequest(BaseModel):
    """Request to record consent."""
    session_id: str
    customer_id: str
    scope: str
    signature_method: str = "verbal"

    model_config = ConfigDict(str_strip_whitespace=True)


class ConsentRecordResponse(BaseModel):
    """Response after recording consent."""
    status: str
    session_id: str

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "recorded",
            "session_id": "sess_abc123"
        }
    })


class MemoryRetrievalResponse(BaseModel):
    """Response with customer memory."""
    customer_id: str
    briefing: Dict[str, Any]
    raw_memories: List[Dict[str, Any]] = []

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "customer_id": "C001",
            "briefing": {},
            "raw_memories": []
        }
    })


class BriefingResponse(BaseModel):
    """Structured briefing for agent."""
    customer_id: str
    customer_name: Optional[str] = None
    session_count: int = 0
    verified_facts: List[Dict[str, Any]] = []
    unverified_facts: List[Dict[str, Any]] = []
    pending_review: List[Dict[str, Any]] = []
    recommended_next_step: str = ""
    flags: List[str] = []
    last_updated: Optional[str] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "customer_id": "C001",
            "customer_name": "Rajesh Kumar",
            "session_count": 3,
            "verified_facts": [],
            "unverified_facts": [],
            "pending_review": [],
            "recommended_next_step": "Document verification",
            "flags": [],
            "last_updated": "2026-03-26T10:00:00Z"
        }
    })


# Phase 6: Memory Quality Layer Models


class FeedbackCorrectionRequest(BaseModel):
    """Officer corrects a wrong fact (income, document, etc.)."""
    session_id: str
    customer_id: str
    fact_id: str
    corrected_value: str
    agent_id: str

    model_config = ConfigDict(str_strip_whitespace=True)


class FeedbackConfirmRequest(BaseModel):
    """Officer confirms a verbal fact with document."""
    session_id: str
    customer_id: str
    fact_id: str
    agent_id: str

    model_config = ConfigDict(str_strip_whitespace=True)


class FeedbackFlagRequest(BaseModel):
    """Officer flags a fact as suspicious (fraud investigation)."""
    session_id: str
    customer_id: str
    fact_id: str
    reason: str
    agent_id: str

    model_config = ConfigDict(str_strip_whitespace=True)


class TimelineEvent(BaseModel):
    """Single session event in customer's memory timeline."""
    session_id: str
    agent_id: str
    timestamp: str
    facts_added: int
    facts_updated: int
    facts_verified: int
    facts_flagged: int

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "S001",
            "agent_id": "AGT_A",
            "timestamp": "2026-03-01T10:00:00Z",
            "facts_added": 3,
            "facts_updated": 0,
            "facts_verified": 0,
            "facts_flagged": 0
        }
    })


class DemoStatusResponse(BaseModel):
    """Status of demo environment."""
    customer_id: str
    fact_count: int
    wal_entries: int

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "customer_id": "C001",
            "fact_count": 8,
            "wal_entries": 4
        }
    })


# Phase 7: Concurrency + Tenant Isolation Models


class BranchRegisterRequest(BaseModel):
    """Request to register a new branch."""
    branch_id: str
    branch_name: str
    region: str

    model_config = ConfigDict(str_strip_whitespace=True)


class BranchInfo(BaseModel):
    """Branch metadata."""
    branch_id: str
    branch_name: str
    region: str
    registered_at: str

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "branch_id": "BR_A",
            "branch_name": "Mumbai Main",
            "region": "west",
            "registered_at": "2026-03-26T10:00:00Z"
        }
    })


class CustomerAssignRequest(BaseModel):
    """Request to assign customer to branch."""
    customer_id: str
    branch_id: str

    model_config = ConfigDict(str_strip_whitespace=True)


class CustomerAssignResponse(BaseModel):
    """Response after customer assignment."""
    status: str  # "assigned" or "already_assigned"
    customer_id: str
    branch_id: str

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "status": "assigned",
            "customer_id": "C001",
            "branch_id": "BR_A"
        }
    })


class BranchListResponse(BaseModel):
    """Response listing all branches."""
    branches: List[BranchInfo]
    count: int

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "branches": [
                {
                    "branch_id": "BR_A",
                    "branch_name": "Mumbai Main",
                    "region": "west",
                    "registered_at": "2026-03-26T10:00:00Z"
                }
            ],
            "count": 1
        }
    })


# Conversational API


class SessionConverseRequest(BaseModel):
    """Request for mid-session conversation."""

    session_id: str
    customer_id: str
    customer_message: str

    model_config = ConfigDict(str_strip_whitespace=True)


class SessionConverseResponse(BaseModel):
    """Response to customer message."""

    agent_response: str
    facts_extracted: List[Dict[str, Any]] = []
    memory_updated: bool = False
    wal_written: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_response": "Based on your combined income of ₹92,000 per month, your indicative eligibility is around ₹48 lakhs...",
                "facts_extracted": [
                    {"type": "income", "value": "65000", "verified": False}
                ],
                "memory_updated": True,
                "wal_written": True,
            }
        }
    )
