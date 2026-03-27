# src/core/mem0_bridge.py
import json
import logging
from typing import List, Dict, Optional
from mem0 import Memory
from .wal import WALLogger
from ..api.middleware import require_consent
from ..infra import RedisCache

logger = logging.getLogger(__name__)


class Mem0Bridge:
    def __init__(self, memory: Memory, wal_logger: WALLogger, bank_id: str = "default", redis_cache: Optional[RedisCache] = None):
        self.memory = memory
        self.wal = wal_logger
        self.bank_id = bank_id
        self.redis_cache = redis_cache

    def _build_mem0_text(self, facts: List[Dict]) -> str:
        """Serialize facts into a compact text payload for Mem0 embedding/search."""
        lines = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            f_type = str(fact.get("type", "unknown"))
            f_value = str(fact.get("value", ""))
            f_source = str(fact.get("source", ""))
            lines.append(f"{f_type}: {f_value} ({f_source})")
        return "\n".join(lines) if lines else "no_facts"

    def _write_mem0(self, composite_user_id: str, agent_id: str, facts: List[Dict]) -> None:
        """Write facts to Mem0, supporting multiple client signatures."""
        payload_text = self._build_mem0_text(facts)

        # Preferred signature in this codebase runtime: add(data, user_id, ...)
        try:
            self.memory.add(payload_text, user_id=composite_user_id, agent_id=agent_id)
            return
        except TypeError:
            # Compatibility with older mem0 variants accepting messages=...
            self.memory.add(
                messages=[{"role": "system", "content": payload_text}],
                user_id=composite_user_id,
                agent_id=agent_id,
            )

    async def add_after_wal(
        self,
        session_id: str,
        customer_id: str,
        agent_id: str,
        facts: List[Dict],
        bank_id: str = "",
    ):
        """
        Write to Mem0 assuming WAL is already persisted by caller.

        This is used by API routes that already enforce WAL-first sequencing.
        """
        effective_bank_id = bank_id or self.bank_id
        composite_user_id = f"{effective_bank_id}::{customer_id}"

        try:
            lock_token = None
            if self.redis_cache is not None:
                lock_token = await self.redis_cache.acquire_lock(customer_id)
                if lock_token is None:
                    logger.warning(
                        "Could not acquire Redis lock for customer=%s; proceeding without lock",
                        customer_id,
                    )

            try:
                self._write_mem0(composite_user_id, agent_id, facts)
            finally:
                if self.redis_cache is not None and lock_token is not None:
                    await self.redis_cache.release_lock(customer_id, lock_token)

            return {"status": "ok", "facts_added": len(facts), "wal_written": True}
        except Exception as e:
            return {"status": "error", "wal_written": True, "error": str(e)}

    @require_consent(scope="home_loan_processing")
    async def add_with_wal(self, session_id: str, customer_id: str, agent_id: str, facts: List[Dict], bank_id: str = ""):
        """
        Step 1: Write WAL
        Step 2: Acquire Redis lock (non-blocking)
        Step 3: Write Mem0
        Step 4: Release Redis lock
        Step 5: Return status
        """
        effective_bank_id = bank_id or self.bank_id
        composite_user_id = f"{effective_bank_id}::{customer_id}"

        try:
            # Step 1: WAL append (crash-safe)
            self.wal.append(session_id, customer_id, agent_id, effective_bank_id, facts)

            # Step 2: Acquire Redis lock (non-blocking for hackathon)
            lock_token = None
            if self.redis_cache is not None:
                lock_token = await self.redis_cache.acquire_lock(customer_id)
                if lock_token is None:
                    logger.warning("Could not acquire Redis lock for customer=%s; proceeding without lock", customer_id)

            # Step 3: mem0.add()
            try:
                self._write_mem0(composite_user_id, agent_id, facts)
            finally:
                # Step 4: Release lock if acquired
                if self.redis_cache is not None and lock_token is not None:
                    await self.redis_cache.release_lock(customer_id, lock_token)

            return {"status": "ok", "facts_added": len(facts)}
        except Exception as e:
            # WAL survives crash; Mem0 write failed but can retry
            return {"status": "error", "wal_written": True, "error": str(e)}
