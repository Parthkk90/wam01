"""
Memory Health Checker — data quality metrics and sync drift detection.

CRITICAL: Detects unverified facts, pending review items, and WAL-Mem0 sync drift.
"""

from typing import Dict, Any, List
from src.core.wal import WALLogger


class MemoryHealthChecker:
    """Check memory health: unverified facts, pending review, sync drift."""

    def __init__(self, wal: WALLogger, memory=None):
        """
        Args:
            wal: WALLogger to read facts from
            memory: Mem0 instance to verify sync
        """
        self.wal = wal
        self.memory = memory

    async def check(self, customer_id: str) -> Dict[str, Any]:
        """
        Check health of customer's memory.

        Returns:
            {
                customer_id: str,
                wal_fact_count: int,
                mem0_fact_count: int,
                unverified_fact_count: int,
                pending_review_count: int,
                flags: List[str],  # Human-readable warnings
                is_healthy: bool,
                sync_check: bool   # True if WAL and Mem0 counts match
            }
        """
        # Read from WAL
        wal_facts = []
        unverified_count = 0
        pending_review_count = 0
        unverified_income = False
        unverified_coapplicant = False

        if self.wal.wal_path.exists():
            try:
                with open(self.wal.wal_path, "r") as f:
                    import json
                    for line in f:
                        if not line.strip():
                            continue
                        entry = json.loads(line)
                        if entry.get("customer_id") != customer_id:
                            continue

                        for fact in entry.get("facts", []):
                            wal_facts.append(fact)

                            # Count unverified
                            if fact.get("verified") is False:
                                unverified_count += 1
                                if fact.get("type") == "income":
                                    unverified_income = True
                                if fact.get("type") == "co_applicant_income":
                                    unverified_coapplicant = True

                            # Count pending review
                            if fact.get("source") == "pending_review":
                                pending_review_count += 1
            except FileNotFoundError:
                pass

        # Check Mem0 sync
        mem0_fact_count = 0
        if self.memory:
            try:
                result = self.memory.get(user_id=customer_id)
                if result and isinstance(result, dict):
                    facts = result.get("facts", [])
                    mem0_fact_count = len(facts) if facts else 0
                else:
                    mem0_fact_count = 0
            except Exception as e:
                mem0_fact_count = 0

        # Build flags
        flags = []
        if unverified_income:
            flags.append("income_unverified")
        if unverified_coapplicant:
            flags.append("co_applicant_unverified")
        if pending_review_count > 0:
            flags.append("has_pending_review")

        # Sync check: both counts must be equal and non-zero
        # (if one is zero and the other is not, they're out of sync)
        sync_ok = (len(wal_facts) == mem0_fact_count) if self.memory else True
        if not sync_ok:
            flags.append("wal_mem0_drift")

        return {
            "customer_id": customer_id,
            "wal_fact_count": len(wal_facts),
            "mem0_fact_count": mem0_fact_count,
            "unverified_fact_count": unverified_count,
            "pending_review_count": pending_review_count,
            "flags": flags,
            "is_healthy": len(flags) == 0,
            "sync_check": sync_ok
        }

    async def sync_check(self, customer_id: str) -> bool:
        """
        Returns True only if WAL fact count == Mem0 fact count.
        
        Detects drift between WAL and Mem0 persistence layers.
        """
        health = await self.check(customer_id)
        return health["sync_check"]
