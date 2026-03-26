"""
Redpanda Consumer Wrapper — integrates consumer with PipelineOrchestrator.

Encapsulates the event loop:
  1. Start RedpandaConsumer.connect()
  2. For each message: deserialize → PipelineOrchestrator.process_entry()
  3. On success: commit offset
  4. On error: log and skip (WAL replay handles recovery)

This is the "glue" between the Redpanda infrastructure and the loan processing pipeline.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
from .redpanda_consumer import RedpandaConsumer
from ..core.pipeline_orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)


class ConsumerOrchestrationService:
    """
    Manages the full consumer lifecycle.

    Responsibilities:
      - Connect/disconnect from Redpanda
      - Deserialize messages
      - Pass to PipelineOrchestrator
      - Commit offsets on success
      - Log errors without crashing
    """

    def __init__(
        self,
        redpanda_consumer: RedpandaConsumer,
        pipeline_orchestrator: PipelineOrchestrator,
        batch_size: int = 1,
    ):
        """
        Args:
            redpanda_consumer: configured RedpandaConsumer instance
            pipeline_orchestrator: PipelineOrchestrator instance
            batch_size: process N messages before commit (for throughput optimization)
        """
        self.consumer = redpanda_consumer
        self.orchestrator = pipeline_orchestrator
        self.batch_size = batch_size
        self._running = False

    async def start(self) -> None:
        """Connect consumer and begin event loop."""
        self._running = True
        await self.consumer.connect()
        logger.info(
            "ConsumerOrchestrationService started: topic=%s group=%s",
            self.consumer.topic,
            self.consumer.group_id,
        )

    async def run(self) -> None:
        """
        Main event loop.

        Runs forever (or until stop() called):
          - Consume messages
          - Process via pipeline
          - Commit offsets
        """
        if not self._running:
            await self.start()

        try:
            await self.consumer.consume(handler=self._handle_entry)
        except asyncio.CancelledError:
            logger.info("ConsumerOrchestrationService run() cancelled")
        except Exception as exc:
            logger.error("Unexpected error in consumer loop: %s", exc, exc_info=True)
        finally:
            await self.stop()

    async def _handle_entry(self, entry: Dict[str, Any]) -> None:
        """
        Handle a single Redpanda message.

        Called by RedpandaConsumer.consume():
          1. Deserialize (already done by consumer)
          2. Process via orchestrator
          3. Log result
          4. Offset commit is done by consumer
        """
        session_id = entry.get("session_id", "unknown")
        customer_id = entry.get("customer_id", "unknown")

        try:
            result = await self.orchestrator.process_entry(entry)

            # Log result based on status
            if result.get("status") == "ok":
                logger.info(
                    "Entry processed OK: session=%s customer=%s status=%s",
                    session_id,
                    customer_id,
                    result["status"],
                )
            elif result.get("status") == "review_required":
                logger.warning(
                    "Entry flagged for review: session=%s customer=%s conflicts=%d suspicious=%d",
                    session_id,
                    customer_id,
                    len(result.get("conflicts", [])),
                    len(result.get("suspicious_facts", [])),
                )
            else:
                logger.error(
                    "Entry error: session=%s customer=%s error=%s",
                    session_id,
                    customer_id,
                    result.get("error", "unknown"),
                )

        except Exception as exc:
            logger.error(
                "Handler error: session=%s customer=%s error=%s",
                session_id,
                customer_id,
                exc,
                exc_info=True,
            )
            # Consumer will commit offset anyway; WAL replay can recover if needed

    async def stop(self) -> None:
        """Clean shutdown."""
        self._running = False
        await self.consumer.close()
        logger.info("ConsumerOrchestrationService stopped")

    async def __aenter__(self):
        """Context manager support."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager cleanup."""
        await self.stop()


async def run_consumer_service(
    brokers: list,
    bank_id: str,
    memory: Any,
    wal: Any,
    redis_cache: Optional[Any] = None,
    group_id: str = "central-processor",
) -> None:
    """
    Standalone helper to boot the entire consumer service.

    Args:
        brokers: ["localhost:9092", ...]
        bank_id: "central" or "branch_001"
        memory: mem0.Memory instance
        wal: WALLogger instance
        redis_cache: RedisCache instance (optional)
        group_id: Kafka consumer group ID
    """
    # Initialize components
    consumer = RedpandaConsumer(brokers=brokers, bank_id=bank_id, group_id=group_id)
    orchestrator = PipelineOrchestrator(
        memory=memory,
        wal=wal,
        redis=redis_cache,
        bank_id=bank_id,
    )
    service = ConsumerOrchestrationService(consumer, orchestrator)

    # Run until interrupted
    try:
        async with service:
            await service.run()
    except KeyboardInterrupt:
        logger.info("Consumer service interrupted by user")
    except Exception as exc:
        logger.error("Consumer service crashed: %s", exc, exc_info=True)
        raise
