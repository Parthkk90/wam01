"""
Feedback API — Officer corrections, confirmations, flags.

Routes:
  POST /feedback/correct
  POST /feedback/confirm
  POST /feedback/flag
  GET /memory/timeline/{customer_id}
  GET /memory/snapshot/{customer_id}/{session_id}
  GET /memory/health/{customer_id}
"""

from fastapi import APIRouter, Depends
from typing import List, Dict, Any, Annotated
from src.api.dependencies import (
    get_feedback_processor,
    get_memory_timeline,
    get_memory_health
)
from src.core.feedback_processor import FeedbackProcessor
from src.core.memory_timeline import MemoryTimeline
from src.core.memory_health import MemoryHealthChecker
from src.api.models import (
    FeedbackCorrectionRequest,
    FeedbackConfirmRequest,
    FeedbackFlagRequest
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("/correct")
async def correct_fact(
    request: FeedbackCorrectionRequest,
    processor: Annotated[FeedbackProcessor, Depends(get_feedback_processor)]
) -> Dict[str, Any]:
    """Officer corrects a wrong fact (WAL-first, confidence=0.99)."""
    result = await processor.process_correction(
        session_id=request.session_id,
        customer_id=request.customer_id,
        fact_id=request.fact_id,
        corrected_value=request.corrected_value,
        agent_id=request.agent_id
    )
    return result


@router.post("/confirm")
async def confirm_fact(
    request: FeedbackConfirmRequest,
    processor: Annotated[FeedbackProcessor, Depends(get_feedback_processor)]
) -> Dict[str, Any]:
    """Officer confirms a verbal fact with document."""
    result = await processor.process_confirmation(
        session_id=request.session_id,
        customer_id=request.customer_id,
        fact_id=request.fact_id,
        agent_id=request.agent_id
    )
    return result


@router.post("/flag")
async def flag_fact(
    request: FeedbackFlagRequest,
    processor: Annotated[FeedbackProcessor, Depends(get_feedback_processor)]
) -> Dict[str, Any]:
    """Officer flags a fact as suspicious (fraud topic publish)."""
    result = await processor.process_flag(
        session_id=request.session_id,
        customer_id=request.customer_id,
        fact_id=request.fact_id,
        reason=request.reason,
        agent_id=request.agent_id
    )
    return result


@router.get("/memory/timeline/{customer_id}")
async def get_timeline(
    customer_id: str,
    timeline: Annotated[MemoryTimeline, Depends(get_memory_timeline)]
) -> Dict[str, Any]:
    """Get timeline of all sessions for a customer."""
    events = await timeline.get_timeline(customer_id=customer_id)
    return {
        "customer_id": customer_id,
        "events": events,
        "count": len(events)
    }


@router.get("/memory/snapshot/{customer_id}/{session_id}")
async def get_snapshot(
    customer_id: str,
    session_id: str,
    timeline: Annotated[MemoryTimeline, Depends(get_memory_timeline)]
) -> Dict[str, Any]:
    """Get memory snapshot as it existed at a point in time."""
    facts = await timeline.get_snapshot(customer_id=customer_id, up_to_session_id=session_id)
    return {
        "customer_id": customer_id,
        "session_id": session_id,
        "facts": facts,
        "fact_count": len(facts)
    }


@router.get("/memory/health/{customer_id}")
async def check_health(
    customer_id: str,
    health: Annotated[MemoryHealthChecker, Depends(get_memory_health)]
) -> Dict[str, Any]:
    """Get memory health report (unverified, pending review, sync drift)."""
    return await health.check(customer_id=customer_id)
