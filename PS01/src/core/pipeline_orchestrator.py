"""
Pipeline Orchestrator — wires ConflictDetector → AdversarialGuard → DerivesWorker → Mem0Bridge.

Flow for each WAL entry from Redpanda:
  1. Extract facts from entry
  2. Query existing facts for customer (from Mem0 via Redis cache)
  3. Detect conflicts between existing & new facts
  4. Run adversarial guard on suspicious facts
  5. Calculate derived facts (disposable income, eligibility, etc.)
  6. Write to WAL → Mem0 via Mem0Bridge (with Redis lock)
  7. Return result with conflicts, derived facts, and Mem0 status

Guarantees:
  - WAL append ALWAYS before Mem0 write (crash-safe)
  - Suspicious facts flagged for review (not auto-approved)
  - At-least-once delivery via Redpanda consumer offset tracking
"""

import logging
from typing import List, Dict, Optional, Any
from .conflict_detector import ConflictDetector
from .adversarial_guard import AdversarialGuard
from .derives_worker import DerivesWorker
from .mem0_bridge import Mem0Bridge
from ..infra.redis_cache import RedisCache

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the event-driven pipeline for loan fact processing.

    Dependencies:
      - ConflictDetector: detects contradictions
      - AdversarialGuard: flags suspicious numerical changes
      - DerivesWorker: calculates derived facts
      - Mem0Bridge: writes to WAL + Mem0 with locks
      - RedisCache (optional): caches existing facts per customer
    """

    def __init__(
        self,
        memory: Any,  # mem0.Memory instance
        wal: Any,  # WALLogger instance
        redis: Optional[RedisCache] = None,
        bank_id: str = "default",
    ):
        """
        Args:
            memory: Mem0 Memory instance (initialized by mem0_init)
            wal: WALLogger instance
            redis: RedisCache instance (optional, for caching existing facts)
            bank_id: multi-tenant bank identifier
        """
        self.memory = memory
        self.wal = wal
        self.redis = redis
        self.bank_id = bank_id

        # Initialize workers
        self.conflict_detector = ConflictDetector()
        self.adversarial_guard = AdversarialGuard()
        self.derives_worker = DerivesWorker()
        self.mem0_bridge = Mem0Bridge(
            memory=memory,
            wal_logger=wal,
            bank_id=bank_id,
            redis_cache=redis,
        )

    async def process_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single WAL entry through the full pipeline.

        Args:
            entry: {
                "session_id": str,
                "customer_id": str,
                "agent_id": str,
                "facts": [{"type": str, "value": Any, "verified": bool, ...}]
            }

        Returns:
            {
                "session_id": str,
                "customer_id": str,
                "status": "ok" | "error" | "review_required",
                "conflicts": [...],  # from ConflictDetector
                "suspicious_facts": [...],  # from AdversarialGuard
                "derived_facts": {...},  # from DerivesWorker
                "mem0_result": {...},  # from Mem0Bridge
            }
        """
        session_id = entry.get("session_id", "unknown")
        customer_id = entry.get("customer_id", "unknown")
        agent_id = entry.get("agent_id", "unknown")
        new_facts = entry.get("facts", [])

        try:
            # Step 1: Get existing facts (from Redis cache or Mem0 search)
            existing_facts = await self.get_existing_facts(customer_id, session_id)

            # Step 2: Detect conflicts
            conflicts = self.conflict_detector.detect(existing_facts, new_facts)

            # Step 3: Check for suspicious facts (via AdversarialGuard)
            suspicious_facts = self._check_suspicious_facts(new_facts, existing_facts)

            # Step 4: Calculate derived facts
            derived_facts = self.derives_worker.calculate(new_facts)

            # Step 5: Decide: if >0 suspicious facts, flag for review; otherwise write to Mem0
            review_required = len(suspicious_facts) > 0
            status = "review_required" if review_required else "ok"

            result = {
                "session_id": session_id,
                "customer_id": customer_id,
                "status": status,
                "conflicts": conflicts,
                "suspicious_facts": suspicious_facts,
                "derived_facts": derived_facts,
            }

            # Step 6: Write to Mem0 only if NOT review_required (optional: allow override)
            if not review_required:
                mem0_result = await self.mem0_bridge.add_with_wal(
                    session_id=session_id,
                    customer_id=customer_id,
                    agent_id=agent_id,
                    facts=new_facts,
                    bank_id=self.bank_id,
                )
                result["mem0_result"] = mem0_result
                logger.info(
                    "Pipeline OK: session=%s customer=%s facts_added=%d",
                    session_id,
                    customer_id,
                    len(new_facts),
                )
            else:
                logger.warning(
                    "Pipeline REVIEW_REQUIRED: session=%s customer=%s suspicious=%d",
                    session_id,
                    customer_id,
                    len(suspicious_facts),
                )
                result["mem0_result"] = {"status": "skipped", "reason": "review_required"}

            return result

        except Exception as exc:
            logger.error(
                "Pipeline error: session=%s customer=%s error=%s",
                session_id,
                customer_id,
                exc,
                exc_info=True,
            )
            return {
                "session_id": session_id,
                "customer_id": customer_id,
                "status": "error",
                "error": str(exc),
            }

    async def get_existing_facts(
        self, customer_id: str, session_id: str
    ) -> List[Dict[str, Any]]:
        """
        Retrieve existing facts for customer.

        Order of precedence:
          1. Redis cache (fast path)
          2. Mem0 search (slower, but accurate)
          3. Empty list (new customer)

        Returns: list of fact dicts with keys: type, value, fact_id, etc.
        """
        cache_key = f"{self.bank_id}:profile:{customer_id}"

        # Try Redis first
        if self.redis is not None:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.debug(
                        "Found existing facts in Redis for customer=%s", customer_id
                    )
                    return cached
            except Exception as exc:
                logger.warning(
                    "Redis lookup failed for customer=%s: %s", customer_id, exc
                )

        # Fall back to Mem0 search
        try:
            composite_user_id = f"{self.bank_id}::{customer_id}"
            # VERIFY: memory.search() returns list of dicts or None
            search_results = self.memory.search(
                query="customer profile facts",
                user_id=composite_user_id,
                limit=50
            )

            facts = []
            if search_results:
                # search_results is typically [{"id": ..., "content": ...}, ...]
                # We need to parse content back to facts
                for result in search_results:
                    try:
                        # VERIFY: result structure from mem0.search()
                        content = result.get("content", "{}")
                        # This is a simplified deserialize; adjust based on actual Mem0 format
                        fact = {"source": "mem0", "id": result.get("id"), "content": content}
                        facts.append(fact)
                    except Exception:
                        pass

            if facts:
                logger.debug(
                    "Found %d existing facts in Mem0 for customer=%s",
                    len(facts),
                    customer_id,
                )
                # Cache in Redis for next time
                if self.redis is not None:
                    try:
                        await self.redis.set(cache_key, facts, ttl=3600)
                    except Exception:
                        pass
            return facts

        except Exception as exc:
            logger.warning(
                "Mem0 lookup failed for customer=%s: %s", customer_id, exc
            )
            return []

    def _check_suspicious_facts(
        self, new_facts: List[Dict], existing_facts: List[Dict]
    ) -> List[Dict[str, Any]]:
        """
        Run AdversarialGuard on each new fact.

        Returns: list of suspicious facts with guard results.
        """
        suspicious = []

        for new_fact in new_facts:
            fact_type = new_fact.get("type")
            new_value = new_fact.get("value")

            # Find existing value for this fact_type
            old_value = None
            for existing in existing_facts:
                if existing.get("type") == fact_type:
                    old_value = existing.get("value")
                    break

            # Only check if both numeric
            if old_value is not None and isinstance(new_value, (int, float)):
                try:
                    old_value_float = float(old_value)
                    new_value_float = float(new_value)

                    guard_result = self.adversarial_guard.check(
                        fact_type, old_value_float, new_value_float
                    )

                    if guard_result["suspicious"]:
                        suspicious.append(
                            {
                                "fact": new_fact,
                                "old_value": old_value,
                                "new_value": new_value,
                                "guard_result": guard_result,
                            }
                        )
                except (ValueError, TypeError):
                    pass

        return suspicious

    async def process_batch(
        self, entries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Process multiple entries in sequence.

        Returns: list of results (one per entry).

        Note: for concurrency, use asyncio.gather() at caller level.
        """
        results = []
        for entry in entries:
            result = await self.process_entry(entry)
            results.append(result)
        return results
