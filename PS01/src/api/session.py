"""Session management FastAPI endpoints."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from uuid import uuid4
import json
import os
import logging
from datetime import datetime, UTC
from typing import Optional, Annotated, Any, Dict

from src.api.models import (
    SessionStartRequest, SessionStartResponse,
    SessionEndRequest, SessionEndResponse,
    SessionConverseRequest, SessionConverseResponse
)
from src.api.dependencies import (
    get_wal_logger, get_mem0_bridge, get_consent_db,
    get_cbs_preseeder, get_briefing_builder,
    get_redis_cache, get_tokenizer
)
from src.core.wal import WALLogger
from src.core.mem0_bridge import Mem0Bridge
from src.api.middleware import ConsentDB
from src.core.cbs_preseeder import CBSPreseeder
from src.core.briefing_builder import BriefingBuilder
from src.core.phi4_compactor import Phi4Compactor
from src.preprocessing.tokenizer import BankingTokenizer

# Logger
logger = logging.getLogger(__name__)

# Bank ID for WAL entries
BANK_ID = os.getenv("BANK_ID", "cooperative_bank_01")

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/start")
async def session_start(
    req: SessionStartRequest,
    background_tasks: BackgroundTasks,
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)],
    mem0_bridge: Annotated[Mem0Bridge, Depends(get_mem0_bridge)],
    consent_db: Annotated[ConsentDB, Depends(get_consent_db)],
    cbs_preseeder: Annotated[CBSPreseeder, Depends(get_cbs_preseeder)],
    briefing_builder: Annotated[BriefingBuilder, Depends(get_briefing_builder)],
    redis_cache: Annotated[Any, Depends(get_redis_cache)]
) -> SessionStartResponse:
    """
    Start a session:
    1. Verify consent
    2. Pre-seed CBS facts
    3. Build briefing
    4. Return session_id + briefing
    """
    # Step 1: Verify consent
    if not req.consent_id:
        return SessionStartResponse(
            session_id=None,
            status="error",
            error_message="consent required"
        )
    
    consent_verified = consent_db.verify_consent(req.consent_id, "session_start")
    if not consent_verified:
        raise HTTPException(status_code=403, detail="consent required")
    
    # Step 2: Generate session_id
    session_id = f"sess_{uuid4().hex[:12]}"
    
    # Step 3: Store in Redis (TTL 2 hours)
    if redis_cache:
        try:
            await redis_cache.set(
                f"session:{session_id}",
                json.dumps({
                    "customer_id": req.customer_id,
                    "agent_id": req.agent_id,
                    "status": "active",
                    "started_at": datetime.now(UTC).isoformat()
                }),
                3600 * 2  # 2 hour TTL
            )
        except Exception:
            pass  # Graceful degradation if Redis unavailable
    
    # Step 4: Pre-seed CBS facts + WAL
    cbs_facts = await cbs_preseeder.preseed(req.customer_id)
    for fact in cbs_facts:
        # WAL FIRST
        wal_logger.append(
            session_id=session_id,
            customer_id=req.customer_id,
            agent_id=req.agent_id,
            bank_id=BANK_ID,
            facts=[fact]
        )
        # TODO: Publish to Redpanda
    
    # Step 5: Build briefing (includes conversational fields)
    briefing = await briefing_builder.build(req.customer_id)
    
    return SessionStartResponse(
        session_id=session_id,
        status="ready",
        briefing=briefing,
        cbs_facts_loaded=len(cbs_facts),
        error_message=None,
        greeting_message=briefing.get("greeting_message", "Welcome! How can I help you today?"),
        context_summary=briefing.get("context_summary", ""),
        suggested_next=briefing.get("suggested_next", ""),
        has_prior_context=briefing.get("has_prior_context", False)
    )


@router.post("/end")
async def session_end(
    req: SessionEndRequest,
    background_tasks: BackgroundTasks,
    redis_cache: Annotated[Any, Depends(get_redis_cache)],
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)],
    tokenizer: Annotated[BankingTokenizer, Depends(get_tokenizer)]
) -> SessionEndResponse:
    """
    End a session:
    1. Get session metadata from Redis
    2. Tokenize & WAL transcript facts
    3. Trigger Phi4 compactor
    4. Mark session as completed
    """
    # Step 1: Get session metadata from Redis
    session_key = f"session:{req.session_id}"
    session_data = None
    
    if redis_cache:
        try:
            session_bytes = await redis_cache.get(session_key)
            if session_bytes:
                session_data = json.loads(session_bytes)
        except Exception:
            pass
    
    if not session_data:
        raise HTTPException(status_code=404, detail="session not found")
    
    customer_id = session_data.get("customer_id")
    agent_id = session_data.get("agent_id")
    facts_count = 0
    
    # Step 2: Process transcript if provided
    if req.transcript:
        # Tokenize FIRST (WAL-first rule)
        tokenized, token_map = tokenizer.tokenize(req.transcript)
        
        # Extract facts (no token_mapping in WAL - it contains raw PII!)
        facts = [
            {
                "type": "transcript",
                "value": tokenized,
                "verified": False,
                "source": "voice_transcribed"
            }
        ]
        
        # WAL FIRST (critical WAL-first guarantee)
        wal_logger.append(
            session_id=req.session_id,
            customer_id=customer_id,
            agent_id=agent_id,
            bank_id=BANK_ID,
            facts=facts
        )
        facts_count = len(facts)
        
        # TODO: Publish to Redpanda topic
    
    # Step 3: Trigger Phi4 compactor in background
    if facts_count > 0:
        background_tasks.add_task(
            _compact_session,
            customer_id=customer_id,
            facts_count=facts_count
        )
    
    # Step 4: Mark session as completed in Redis
    if redis_cache and session_data:
        session_data["status"] = "completed"
        try:
            await redis_cache.set(
                session_key,
                json.dumps(session_data),
                3600 * 2
            )
        except Exception:
            pass
    
    return SessionEndResponse(
        status="completed",
        facts_count=facts_count,
        compact_triggered=facts_count > 0,
        transcript_archived=bool(req.transcript)
    )


@router.post("/add-fact")
async def session_add_fact(
    session_id: str,
    customer_id: str,
    agent_id: str,
    fact_type: str,
    fact_value: str,
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)],
    redis_cache: Annotated[Any, Depends(get_redis_cache)]
) -> Dict[str, Any]:
    """
    Add a single fact to session:
    1. WAL FIRST
    2. Publish to Redpanda
    3. Invalidate briefing cache
    """
    fact = {
        "type": fact_type,
        "value": fact_value,
        "verified": False,
        "source": "voice_input"
    }
    
    # Step 1: WAL FIRST (critical)
    wal_logger.append(
        session_id=session_id,
        customer_id=customer_id,
        agent_id=agent_id,
        bank_id=BANK_ID,
        facts=[fact]
    )
    
    # Step 2: TODO: Publish to Redpanda
    
    # Step 3: Invalidate cache
    if redis_cache:
        try:
            await redis_cache.delete(f"briefing:{customer_id}")
        except Exception:
            pass
    
    fact_id = f"fact_{uuid4().hex[:8]}"
    return {
        "fact_id": fact_id,
        "wal_written": True,
        "status": "queued"
    }


@router.get("/memory/{customer_id}")
async def get_session_memory(
    customer_id: str,
    redis_cache: Annotated[Any, Depends(get_redis_cache)],
    briefing_builder: Annotated[BriefingBuilder, Depends(get_briefing_builder)]
) -> Dict[str, Any]:
    """
    Retrieve session memory:
    1. Check Redis cache
    2. On miss: BriefingBuilder.build()
    """
    cache_key = f"briefing:{customer_id}"
    
    # Step 1: Check cache
    if redis_cache:
        try:
            cached = await redis_cache.get(cache_key)
            if cached:
                if isinstance(cached, bytes):
                    return json.loads(cached.decode())
                elif isinstance(cached, dict):
                    return cached
                elif isinstance(cached, str):
                    return json.loads(cached)
        except Exception:
            pass
    
    # Step 2: Cache miss - build from briefing_builder
    briefing = await briefing_builder.build(customer_id)
    return briefing


# Background task
async def _compact_session(customer_id: str, facts_count: int):
    """Compact session facts in background (stub)."""
    try:
        compactor = Phi4Compactor()
        # await compactor.compact(...)  # Would call Phi4
    except Exception:
        pass


@router.post("/converse")
async def session_converse(
    req: SessionConverseRequest,
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)],
    tokenizer: Annotated[BankingTokenizer, Depends(get_tokenizer)],
) -> SessionConverseResponse:
    """
    Mid-session conversational exchange.
    Agent sends customer message, system responds with agent guidance.
    """
    import re
    from src.core.conversation_engine import ConversationEngine

    # Step 1: Tokenize customer message (PII safety)
    tokenized_msg, token_map = tokenizer.tokenize(req.customer_message)

    # Step 2: Extract facts (regex-based, simple patterns)
    facts_extracted = []

    # Income pattern: 2-5 digits followed by k/lakh/rupees/thousand
    income_match = re.search(
        r"(\d{2,5})\s*(k|lakh|rupees|thousand)?", req.customer_message, re.IGNORECASE
    )
    if income_match:
        amount = income_match.group(1)
        if int(amount) >= 10:  # Filter out noise  (at least 10)
            facts_extracted.append(
                {
                    "type": "income",
                    "value": amount,
                    "verified": False,
                    "source": "customer_verbal",
                }
            )

    # Name patterns: "my wife/husband/co-applicant {name}"
    name_match = re.search(
        r"(?:wife|husband|co.?applicant|spouse)\s+([A-Za-z]+)", req.customer_message
    )
    if name_match:
        facts_extracted.append(
            {
                "type": "co_applicant_name",
                "value": name_match.group(1),
                "verified": False,
                "source": "customer_verbal",
            }
        )

    # Step 3: Generate agent response
    engine = ConversationEngine()
    agent_response = engine.generate_next_step(facts_extracted, [])

    # Step 4: WAL append if facts extracted (CRITICAL: WAL first)
    wal_written = False
    if facts_extracted:
        try:
            wal_logger.append(
                session_id=req.session_id,
                customer_id=req.customer_id,
                agent_id="voice_input",
                bank_id=os.getenv("BANK_ID", "cooperative_bank_01"),
                facts=facts_extracted,
            )
            wal_written = True
            # TODO: Publish to Redpanda
        except Exception as e:
            logger.warning(f"Failed to write WAL: {e}")

    return SessionConverseResponse(
        agent_response=agent_response,
        facts_extracted=facts_extracted,
        memory_updated=False,  # TODO: Mem0 write after verification
        wal_written=wal_written,
    )
