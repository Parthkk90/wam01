"""FastAPI dependency injection for core services."""

import asyncio
import logging
import os
from pathlib import Path

from src.core.wal import WALLogger
from src.core.mem0_bridge import Mem0Bridge
from src.core.cbs_preseeder import CBSPreseeder
from src.core.briefing_builder import BriefingBuilder
from src.core.briefing_speech import BriefingSpeechBuilder
from src.core.conversation_agent import ConversationAgent
from src.core.feedback_processor import FeedbackProcessor
from src.core.memory_timeline import MemoryTimeline
from src.core.memory_health import MemoryHealthChecker
from src.core.demo_seeder import DemoSeeder
from src.core.evaluation_harness import EvaluationHarness
from src.core.branch_lock_manager import BranchLockManager
from src.core.tenant_registry import TenantRegistry
from src.api.middleware import ConsentDB
from src.preprocessing.tokenizer import BankingTokenizer
from src.infra.redpanda_producer import RedpandaProducer
from src.infra.redpanda_consumer import RedpandaConsumer
import redis.asyncio as redis
from typing import Optional, Annotated
from fastapi import Depends

logger = logging.getLogger(__name__)


# Singleton instances (in production, use proper DI container)
_wal_logger: Optional[WALLogger] = None
_mem0_bridge: Optional[Mem0Bridge] = None
_cbs_preseeder: Optional[CBSPreseeder] = None
_consent_db: Optional[ConsentDB] = None
_redis_cache: Optional[redis.Redis] = None
_briefing_builder: Optional[BriefingBuilder] = None
_briefing_speech_builder: Optional[BriefingSpeechBuilder] = None
_conversation_agent: Optional[ConversationAgent] = None
_tokenizer: Optional[BankingTokenizer] = None
_feedback_processor: Optional[FeedbackProcessor] = None
_memory_timeline: Optional[MemoryTimeline] = None
_memory_health: Optional[MemoryHealthChecker] = None
_demo_seeder: Optional[DemoSeeder] = None
_evaluation_harness: Optional[EvaluationHarness] = None
_branch_lock_manager: Optional[BranchLockManager] = None
_tenant_registry: Optional[TenantRegistry] = None
_redpanda_producer: Optional[RedpandaProducer] = None
_redpanda_consumer: Optional[RedpandaConsumer] = None


def _parse_redpanda_brokers() -> list[str]:
    brokers_raw = os.getenv("REDPANDA_BROKERS", "localhost:9092")
    return [b.strip() for b in brokers_raw.split(",") if b.strip()]


async def get_wal_logger() -> WALLogger:
    """Get WALLogger instance."""
    global _wal_logger
    if _wal_logger is None:
        project_root = Path(__file__).resolve().parents[2]
        default_wal = project_root / "data" / "wal" / "ps01_wal.jsonl"
        wal_path = os.getenv("WAL_PATH", str(default_wal))
        _wal_logger = WALLogger(wal_path=wal_path)
    return _wal_logger


async def get_mem0_bridge() -> Mem0Bridge:
    """Get Mem0Bridge instance."""
    global _mem0_bridge
    if _mem0_bridge is None:
        from src.infra.mem0_init import init_mem0
        memory = init_mem0()
        wal_logger = await get_wal_logger()
        _mem0_bridge = Mem0Bridge(memory=memory, wal_logger=wal_logger)
    return _mem0_bridge


async def get_cbs_preseeder() -> CBSPreseeder:
    """Get CBSPreseeder instance."""
    global _cbs_preseeder
    if _cbs_preseeder is None:
        # Create a mock CBS API with get_customer method
        class MockCBSAPI:
            async def get_customer(self, customer_id: str):
                """Mock CBS lookup - returns None for new customers."""
                return None  # Simulates new customer / not found in CBS
        
        _cbs_preseeder = CBSPreseeder(cbs_api=MockCBSAPI())
    return _cbs_preseeder


async def get_consent_db() -> ConsentDB:
    """Get ConsentDB instance."""
    global _consent_db
    if _consent_db is None:
        _consent_db = ConsentDB(db_path="/tmp/ps01_consent.db")
    return _consent_db


async def get_redis_cache() -> redis.Redis:
    """Get Redis async client."""
    global _redis_cache
    if _redis_cache is None:
        try:
            _redis_cache = await redis.from_url(
                os.getenv("REDIS_URL", "redis://localhost:6380")
            )
        except Exception:
            # If Redis is not available, return None (graceful degradation)
            return None
    return _redis_cache


async def get_redpanda_producer() -> Optional[RedpandaProducer]:
    """Get Redpanda producer instance (graceful degradation when broker unavailable)."""
    global _redpanda_producer

    if _redpanda_producer is None:
        bank_id = os.getenv("BANK_ID", "cooperative_bank_01")
        _redpanda_producer = RedpandaProducer(
            brokers=_parse_redpanda_brokers(),
            bank_id=bank_id,
        )

    if getattr(_redpanda_producer, "_producer", None) is None:
        connect_timeout = float(os.getenv("REDPANDA_CONNECT_TIMEOUT", "2"))
        try:
            await asyncio.wait_for(_redpanda_producer.connect(), timeout=connect_timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redpanda producer unavailable: %s", exc)
            return None

    return _redpanda_producer


async def get_redpanda_consumer() -> RedpandaConsumer:
    """Get Redpanda consumer instance for background orchestration."""
    global _redpanda_consumer

    if _redpanda_consumer is None:
        bank_id = os.getenv("BANK_ID", "cooperative_bank_01")
        group_id = os.getenv("REDPANDA_GROUP_ID", "central-processor")
        _redpanda_consumer = RedpandaConsumer(
            brokers=_parse_redpanda_brokers(),
            bank_id=bank_id,
            group_id=group_id,
        )

    return _redpanda_consumer


async def get_briefing_builder(
    mem0_bridge: Annotated[Mem0Bridge, Depends(get_mem0_bridge)],
    redis_cache: Annotated[Optional[redis.Redis], Depends(get_redis_cache)],
    wal_logger: Annotated[WALLogger, Depends(get_wal_logger)]
) -> BriefingBuilder:
    """Get BriefingBuilder instance."""
    global _briefing_builder
    if _briefing_builder is None:
        mem0 = mem0_bridge or await get_mem0_bridge()
        cache = redis_cache or await get_redis_cache()
        wal = wal_logger or await get_wal_logger()
        _briefing_builder = BriefingBuilder(memory=mem0, redis_cache=cache, wal_logger=wal)
    return _briefing_builder


async def get_tokenizer() -> BankingTokenizer:
    """Get BankingTokenizer instance."""
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = BankingTokenizer()
    return _tokenizer


# Phase 6: Memory Quality Layer
async def get_feedback_processor(
    wal: Annotated[WALLogger, Depends(get_wal_logger)],
    mem0: Annotated[Mem0Bridge, Depends(get_mem0_bridge)],
    redis: Annotated[Optional[redis.Redis], Depends(get_redis_cache)]
) -> FeedbackProcessor:
    """Get FeedbackProcessor instance."""
    global _feedback_processor
    if _feedback_processor is None:
        w = wal or await get_wal_logger()
        m = mem0 or await get_mem0_bridge()
        r = redis or await get_redis_cache()
        _feedback_processor = FeedbackProcessor(wal=w, memory=m, redis=r)
    return _feedback_processor


async def get_memory_timeline(
    wal: Annotated[WALLogger, Depends(get_wal_logger)],
    mem0: Annotated[Mem0Bridge, Depends(get_mem0_bridge)]
) -> MemoryTimeline:
    """Get MemoryTimeline instance."""
    global _memory_timeline
    if _memory_timeline is None:
        w = wal or await get_wal_logger()
        m = mem0 or await get_mem0_bridge()
        _memory_timeline = MemoryTimeline(wal=w, memory=m)
    return _memory_timeline


async def get_memory_health(
    wal: Annotated[WALLogger, Depends(get_wal_logger)],
    mem0: Annotated[Mem0Bridge, Depends(get_mem0_bridge)]
) -> MemoryHealthChecker:
    """Get MemoryHealthChecker instance."""
    global _memory_health
    if _memory_health is None:
        w = wal or await get_wal_logger()
        m = mem0 or await get_mem0_bridge()
        _memory_health = MemoryHealthChecker(wal=w, memory=m)
    return _memory_health


async def get_demo_seeder(
    wal: Annotated[WALLogger, Depends(get_wal_logger)],
    mem0: Annotated[Mem0Bridge, Depends(get_mem0_bridge)],
    redis: Annotated[Optional[redis.Redis], Depends(get_redis_cache)]
) -> DemoSeeder:
    """Get DemoSeeder instance."""
    global _demo_seeder
    if _demo_seeder is None:
        w = wal or await get_wal_logger()
        m = mem0 or await get_mem0_bridge()
        r = redis or await get_redis_cache()
        _demo_seeder = DemoSeeder(wal=w, memory=m, redis=r)
    return _demo_seeder


async def get_evaluation_harness() -> EvaluationHarness:
    """Get EvaluationHarness instance."""
    global _evaluation_harness
    if _evaluation_harness is None:
        _evaluation_harness = EvaluationHarness()
    return _evaluation_harness


# Phase 7: Concurrency + Tenant Isolation
async def get_branch_lock_manager(
    redis: Annotated[Optional[redis.Redis], Depends(get_redis_cache)]
) -> BranchLockManager:
    """Get BranchLockManager instance."""
    global _branch_lock_manager
    if _branch_lock_manager is None:
        r = redis or await get_redis_cache()
        _branch_lock_manager = BranchLockManager(r)
    return _branch_lock_manager


async def get_tenant_registry(
    redis: Annotated[Optional[redis.Redis], Depends(get_redis_cache)]
) -> TenantRegistry:
    """Get TenantRegistry instance."""
    global _tenant_registry
    if _tenant_registry is None:
        r = redis or await get_redis_cache()
        _tenant_registry = TenantRegistry(r)
    return _tenant_registry


async def get_briefing_speech_builder() -> BriefingSpeechBuilder:
    """Get BriefingSpeechBuilder instance (reads OLLAMA_API from env)."""
    global _briefing_speech_builder
    if _briefing_speech_builder is None:
        _briefing_speech_builder = BriefingSpeechBuilder()
    return _briefing_speech_builder


async def get_conversation_agent(
    wal: Annotated[WALLogger, Depends(get_wal_logger)],
    mem0: Annotated[Mem0Bridge, Depends(get_mem0_bridge)]
) -> ConversationAgent:
    """Get ConversationAgent instance (injects WAL and Mem0 for fact updates)."""
    global _conversation_agent
    if _conversation_agent is None:
        _conversation_agent = ConversationAgent(wal_logger=wal, mem0_bridge=mem0)
    return _conversation_agent
