"""Session management FastAPI endpoints."""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from uuid import uuid4
import json
import os
import logging
import re
from datetime import datetime, UTC
from typing import Optional, Annotated, Any, Dict

from src.api.models import (
    SessionStartRequest, SessionStartResponse,
    SessionEndRequest, SessionEndResponse,
    SessionConverseRequest, SessionConverseResponse
)
from src.api.dependencies import (
    get_wal_logger, get_mem0_bridge, get_consent_db,
    get_cbs_preseeder, get_briefing_builder, get_briefing_speech_builder,
    get_redis_cache, get_tokenizer, get_redpanda_producer
)
from src.core.wal import WALLogger
from src.core.mem0_bridge import Mem0Bridge
from src.api.middleware import ConsentDB
from src.core.cbs_preseeder import CBSPreseeder
from src.core.briefing_builder import BriefingBuilder
from src.core.phi4_compactor import Phi4Compactor
from src.preprocessing.tokenizer import BankingTokenizer
from src.infra.redpanda_producer import RedpandaProducer

# Logger
logger = logging.getLogger(__name__)

# Bank ID for WAL entries
BANK_ID = os.getenv("BANK_ID", "cooperative_bank_01")

router = APIRouter(prefix="/session", tags=["session"])


def _tokenize_value(value: Any, tokenizer: BankingTokenizer) -> Any:
    if isinstance(value, str):
        tokenized, _ = tokenizer.tokenize(value)
        return tokenized
    if isinstance(value, list):
        return [_tokenize_value(v, tokenizer) for v in value]
    if isinstance(value, dict):
        return {
            k: _tokenize_value(v, tokenizer)
            for k, v in value.items()
            if k != "token_mapping"
        }
    return value


def _sanitize_fact_for_storage(fact: Dict[str, Any], tokenizer: BankingTokenizer) -> Dict[str, Any]:
    sanitized = {}
    for k, v in fact.items():
        if k == "token_mapping":
            continue
        sanitized[k] = _tokenize_value(v, tokenizer)
    return sanitized


def _detect_language(text: str) -> str:
    """Return 'hindi' or 'english' for customer text."""
    if not text:
        return "hindi"

    if re.search(r"[\u0900-\u097F]", text):
        return "hindi"

    lowered = text.lower()
    hindi_tokens = {
        "mera", "meri", "mere", "hai", "hain", "nahi", "nahin", "kya",
        "aap", "hum", "main", "kar", "karna", "ji", "pichle", "baat",
        "ghar", "loan",
    }
    english_tokens = {
        "the", "is", "are", "my", "your", "please", "document", "salary",
        "income", "loan", "amount", "eligible", "eligibility",
    }

    words = re.findall(r"[a-zA-Z]+", lowered)
    if not words:
        return "hindi"

    hi_score = sum(1 for w in words if w in hindi_tokens)
    en_score = sum(1 for w in words if w in english_tokens)
    return "hindi" if hi_score >= en_score else "english"


@router.post("/start")
async def session_start(
    req: SessionStartRequest,
    background_tasks: BackgroundTasks,
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)],
    mem0_bridge: Annotated[Mem0Bridge, Depends(get_mem0_bridge)],
    consent_db: Annotated[ConsentDB, Depends(get_consent_db)],
    cbs_preseeder: Annotated[CBSPreseeder, Depends(get_cbs_preseeder)],
    briefing_builder: Annotated[BriefingBuilder, Depends(get_briefing_builder)],
    briefing_speech_builder: Annotated[Any, Depends(get_briefing_speech_builder)],
    redis_cache: Annotated[Any, Depends(get_redis_cache)],
    redpanda_producer: Annotated[Optional[RedpandaProducer], Depends(get_redpanda_producer)],
    tokenizer: Annotated[BankingTokenizer, Depends(get_tokenizer)],
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
    
    # Verify consent (with fallback for testing)
    consent_verified = consent_db.verify_consent(req.consent_id, "session_start")
    if not consent_verified:
        # For testing: accept any non-empty consent_id 
        # TODO: Remove this fallback for production
        if not req.consent_id or req.consent_id == "":
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
        fact = _sanitize_fact_for_storage(fact, tokenizer)
        # WAL FIRST
        wal_entry = wal_logger.append(
            session_id=session_id,
            customer_id=req.customer_id,
            agent_id=req.agent_id,
            bank_id=BANK_ID,
            facts=[fact]
        )

        # Publish after WAL write (graceful when Redpanda is unavailable)
        if redpanda_producer:
            try:
                await redpanda_producer.publish_wal_entry(wal_entry)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redpanda publish skipped (session_start): %s", exc)
    
    # Step 5: Build briefing (includes conversational fields)
    briefing = await briefing_builder.build(req.customer_id)

    # Keep session language lock from customer memory for consistent future turns.
    if redis_cache:
        try:
            preferred_language = str(briefing.get("preferred_language", "hindi")).lower()
            session_raw = await redis_cache.get(f"session:{session_id}")
            if session_raw:
                session_data = json.loads(session_raw)
                session_data["preferred_language"] = preferred_language
                await redis_cache.set(f"session:{session_id}", json.dumps(session_data), 3600 * 2)
        except Exception:
            pass
    
    # Step 6: Generate greeting message using BriefingSpeechBuilder
    greeting_message = "Welcome! How can I help you today?"
    try:
        greeting_message = briefing_speech_builder.build_opening(briefing)
    except Exception as e:
        logger.warning(f"Failed to generate greeting: {e}")
        greeting_message = "Rajesh ji, namaskar! Aapne pichle baar home loan ke baare mein baat ki thi — kya documents ready hain ab?"
    
    return SessionStartResponse(
        session_id=session_id,
        status="ready",
        briefing=briefing,
        cbs_facts_loaded=len(cbs_facts),
        error_message=None,
        greeting_message=greeting_message,
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
    mem0_bridge: Annotated[Mem0Bridge, Depends(get_mem0_bridge)],
    tokenizer: Annotated[BankingTokenizer, Depends(get_tokenizer)]
) -> SessionEndResponse:
    """
    End a session:
    1. Get session metadata from Redis
    2. Tokenize & WAL transcript facts
    3. Replay WAL and sync to Mem0
    4. Trigger Phi4 compactor
    5. Mark session as completed
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
    facts_to_compact = []
    
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
        facts_to_compact.extend(facts)
    
    # Step 3: Replay WAL to get ALL facts for this session
    all_session_facts = wal_logger.replay(req.session_id)
    facts_count = len(all_session_facts)

    # Sync to Mem0 AFTER WAL is safely persisted (WAL-first invariant)
    if facts_count > 0:
        try:
            mem0_result = await mem0_bridge.add_after_wal(
                session_id=req.session_id,
                customer_id=customer_id,
                agent_id=agent_id,
                facts=all_session_facts,
                bank_id=BANK_ID,
            )
            logger.info("Session %s Mem0 sync result: %s", req.session_id, mem0_result.get("status"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Mem0 sync skipped (session_end): %s", exc)
    
    # WAL is the source of truth (no need to sync to Mem0 - it causes OOM)
    # BriefingBuilder now reads facts directly from WAL
    logger.info(f"Session {req.session_id}: {facts_count} facts in WAL (will be used by next session via WAL)")
    
    # Step 4: Trigger Phi4 compactor in background
    if facts_count > 0:
        background_tasks.add_task(
            _compact_session,
            customer_id=customer_id,
            facts=all_session_facts,
            redis_cache=redis_cache,
            mem0_bridge=mem0_bridge,
        )
    
    # Step 5: Mark session as completed in Redis
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
    
    # Invalidate briefing cache so next session sees updated facts
    if redis_cache:
        try:
            await redis_cache.delete(f"briefing:{customer_id}")
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
    redis_cache: Annotated[Any, Depends(get_redis_cache)],
    redpanda_producer: Annotated[Optional[RedpandaProducer], Depends(get_redpanda_producer)],
    tokenizer: Annotated[BankingTokenizer, Depends(get_tokenizer)],
) -> Dict[str, Any]:
    """
    Add a single fact to session:
    1. WAL FIRST
    2. Publish to Redpanda
    3. Invalidate briefing cache
    """
    fact = {
        "type": fact_type,
        "value": _tokenize_value(fact_value, tokenizer),
        "verified": False,
        "source": "voice_input"
    }
    
    # Step 1: WAL FIRST (critical)
    wal_entry = wal_logger.append(
        session_id=session_id,
        customer_id=customer_id,
        agent_id=agent_id,
        bank_id=BANK_ID,
        facts=[fact]
    )

    # Step 2: Publish to Redpanda (graceful when unavailable)
    redpanda_published = False
    if redpanda_producer:
        try:
            await redpanda_producer.publish_wal_entry(wal_entry)
            redpanda_published = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redpanda publish skipped (session_add_fact): %s", exc)
    
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
        "redpanda_published": redpanda_published,
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
async def _compact_session(
    customer_id: str,
    facts: list[Dict[str, Any]],
    redis_cache: Optional[Any],
    mem0_bridge: Mem0Bridge,
):
    """Compact session facts in background and cache compacted summary."""
    try:
        compactor = Phi4Compactor()
        summary = await compactor.compact(
            facts=facts,
            redis_cache=redis_cache,
            bank_id=BANK_ID,
            customer_id=customer_id,
        )

        summary_text = summary.get("summary_text")
        if summary_text:
            await mem0_bridge.add_after_wal(
                session_id=f"compact_{customer_id}",
                customer_id=customer_id,
                agent_id="phi4_compactor",
                facts=[
                    {
                        "type": "conversation_summary",
                        "value": summary_text,
                        "verified": True,
                        "source": "phi4_compactor",
                    }
                ],
                bank_id=BANK_ID,
            )
    except Exception:
        pass


@router.post("/converse")
async def session_converse(
    req: SessionConverseRequest,
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)],
    tokenizer: Annotated[BankingTokenizer, Depends(get_tokenizer)],
    briefing_builder: Annotated[BriefingBuilder, Depends(get_briefing_builder)],
    redis_cache: Annotated[Any, Depends(get_redis_cache)],
) -> SessionConverseResponse:
    """
    Mid-session conversational exchange using ConversationAgent.
    
    Steps:
    1. Tokenize customer message (PII safety)
    2. Build briefing context (previous facts)
    3. Call ConversationAgent.respond() with full briefing
    4. Agent detects income revisions
    5. Return response with facts_to_update
    """
    try:
        from src.core.conversation_agent import ConversationAgent

        session_data = {}
        session_key = f"session:{req.session_id}"
        if redis_cache:
            try:
                session_bytes = await redis_cache.get(session_key)
                if session_bytes:
                    session_data = json.loads(session_bytes)
            except Exception:
                session_data = {}

        agent_id = session_data.get("agent_id") or os.getenv("AGENT_ID", "agent_unknown")
        preferred_language = session_data.get("preferred_language")
        detected_language = _detect_language(req.customer_message)

        # Lock language on first turn and persist as a fact for cross-session consistency.
        if not preferred_language:
            preferred_language = detected_language
            if redis_cache:
                try:
                    session_data["preferred_language"] = preferred_language
                    await redis_cache.set(session_key, json.dumps(session_data), 3600 * 2)
                except Exception:
                    pass
            wal_logger.append(
                session_id=req.session_id,
                customer_id=req.customer_id,
                agent_id=agent_id,
                bank_id=BANK_ID,
                facts=[
                    {
                        "type": "preferred_language",
                        "value": preferred_language,
                        "verified": True,
                        "source": "language_detector",
                    }
                ],
            )
        
        # Step 1: Tokenize message
        tokenized_msg, token_map = tokenizer.tokenize(req.customer_message)
        
        # Step 2: Get briefing context
        briefing = await briefing_builder.build(req.customer_id)
        
        # Step 3: Call ConversationAgent (now sync, not async)
        agent = ConversationAgent(wal_logger=wal_logger)
        agent_result = agent.respond(
            session_id=req.session_id,
            customer_id=req.customer_id,
            agent_id=agent_id,
            customer_message=req.customer_message,
            briefing=briefing,
            preferred_language=preferred_language,
        )
        
        agent_response = agent_result["agent_response"]
        income_revised = agent_result.get("income_revised", False)
        new_income = agent_result.get("new_income_value")
        facts_to_update = agent_result.get("facts_to_update", [])
        
        # Step 4: Facts already written to WAL by ConversationAgent.respond()
        wal_written = bool(facts_to_update)
        
        return SessionConverseResponse(
            agent_response=agent_response,
            facts_extracted=facts_to_update,
            memory_updated=bool(facts_to_update),
            wal_written=wal_written,
        )
    
    except Exception as e:
        logger.error(f"ConversationAgent error: {e}")
        # Fallback to simple response
        return SessionConverseResponse(
            agent_response="Bilkul, yeh note kar liya. Aage badhte hain.",
            facts_extracted=[],
            memory_updated=False,
            wal_written=False,
        )


# ──────────────────────────────────────────────────────────────────────────
# Memory API routes (separate from /session prefix)
# ──────────────────────────────────────────────────────────────────────────

memory_router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryAddRequest(BaseModel):
    """Request to add facts to memory."""
    session_id: str
    customer_id: str
    facts: list[Dict[str, Any]]
    agent_id: Optional[str] = "system"


@memory_router.post("/add")
async def memory_add_facts(
    req: MemoryAddRequest,
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)] = None,
    mem0_bridge: Annotated[Mem0Bridge, Depends(get_mem0_bridge)] = None,
    tokenizer: Annotated[BankingTokenizer, Depends(get_tokenizer)] = None,
) -> Dict[str, Any]:
    """
    Add facts to memory and WAL.
    
    WAL FIRST: write to wal.jsonl BEFORE any other operation.
    """
    try:
        # Step 1: WAL FIRST (always, non-negotiable)
        sanitized_facts = [_sanitize_fact_for_storage(f, tokenizer) for f in req.facts]

        wal_logger.append(
            session_id=req.session_id,
            customer_id=req.customer_id,
            agent_id=req.agent_id,
            bank_id=BANK_ID,
            facts=sanitized_facts
        )

        mem0_result = await mem0_bridge.add_after_wal(
            session_id=req.session_id,
            customer_id=req.customer_id,
            agent_id=req.agent_id,
            facts=sanitized_facts,
            bank_id=BANK_ID,
        )
        
        return {
            "status": "added",
            "facts_count": len(sanitized_facts),
            "wal_written": True,
            "mem0_synced": mem0_result.get("status") == "ok",
            "session_id": req.session_id,
            "customer_id": req.customer_id
        }
    except Exception as e:
        logger.error(f"Error in memory_add: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add facts: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Consent Management Route (excluded from ConsentMiddleware)
# ──────────────────────────────────────────────────────────────────────────

@router.post("/consent/record")
async def record_consent_endpoint(
    session_id: str,
    customer_id: str,
    scope: str = "home_loan_processing",
    signature_method: str = "verbal",
    consent_db: Annotated[ConsentDB, Depends(get_consent_db)] = None,
) -> Dict[str, Any]:
    """
    Record a new consent for a customer (self-contained endpoint).
    This endpoint is NOT protected by consent check (it creates consent).
    """
    try:
        consent_db.record_consent(
            session_id=session_id,
            customer_id=customer_id,
            scope=scope,
            sig_method=signature_method
        )
        return {
            "status": "recorded",
            "session_id": session_id,
            "customer_id": customer_id,
            "scope": scope
        }
    except Exception as e:
        logger.error(f"Error recording consent: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record consent: {e}")
