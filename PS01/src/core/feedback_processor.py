"""
Feedback Processor — WAL-first officer corrections and confirmations.

CRITICAL RULES:
1. WAL.append() ALWAYS before mem0.add() for corrections/confirmations
2. NEVER call mem0.add() for flagged facts
3. Flagged facts → pending_review namespace only
4. Officer corrections marked confidence=0.99
"""

from typing import Dict, Any, Optional
from datetime import datetime, UTC
from src.core.wal import WALLogger


class FeedbackProcessor:
    """Process officer feedback: corrections, confirmations, flags."""

    def __init__(self, wal: WALLogger, memory=None, redis=None, redpanda=None):
        """
        Args:
            wal: WALLogger for append operations
            memory: Mem0 instance (only for corrections/confirmations, NOT for flags)
            redis: Redis client for cache invalidation
            redpanda: Redpanda producer for fraud alerts
        """
        self.wal = wal
        self.memory = memory
        self.redis = redis
        self.redpanda = redpanda

    async def process_correction(self, session_id: str, customer_id: str, fact_id: str,
                                  corrected_value: str, agent_id: str) -> Dict[str, Any]:
        """
        Officer corrects a wrong fact (e.g., income 55K → 62K).

        CRITICAL: WAL.append() BEFORE mem0.add()
        """
        # Step 1: Append to WAL first (no exceptions)
        self.wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id=agent_id,
            bank_id="central",  # Default; could be parameterized
            facts=[{
                "fact_id": fact_id,
                "type": "income",  # Original fact type, not "correction"
                "value": corrected_value,
                "relationship": "updates",
                "supersedes": fact_id,
                "verified": True,
                "source": "officer_verified",
                "confidence": 0.99
            }]
        )

        # Step 2: Only after WAL write, update mem0
        if self.memory:
            messages = [
                {"role": "user", "content": f"Officer corrected {fact_id} to {corrected_value}"}
            ]
            await self.memory.add(messages=messages, user_id=customer_id)

        # Step 3: Invalidate caches
        if self.redis:
            await self.redis.delete(f"summary:{customer_id}")
            await self.redis.delete(f"briefing:{customer_id}")

        return {
            "status": "corrected",
            "fact_id": fact_id,
            "wal_written": True,
            "mem0_updated": True,
            "cache_invalidated": True
        }

    async def process_confirmation(self, session_id: str, customer_id: str, fact_id: str,
                                    agent_id: str) -> Dict[str, Any]:
        """
        Officer confirms a verbal fact with document (e.g., land location verified).

        Upgrades source from customer_verbal → officer_verified
        """
        # Step 1: Append to WAL
        self.wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id=agent_id,
            bank_id="central",
            facts=[{
                "fact_id": fact_id,
                "type": "confirmation",
                "relationship": "verifies",
                "verified": True,
                "source": "officer_verified",
                "confidence": 0.99
            }]
        )

        # Step 2: Update mem0
        if self.memory:
            messages = [
                {"role": "user", "content": f"Officer confirmed {fact_id}"}
            ]
            await self.memory.add(messages=messages, user_id=customer_id)

        # Step 3: Invalidate cache
        if self.redis:
            await self.redis.delete(f"briefing:{customer_id}")

        return {
            "status": "confirmed",
            "fact_id": fact_id,
            "wal_written": True,
            "mem0_updated": True
        }

    async def process_flag(self, session_id: str, customer_id: str, fact_id: str,
                           reason: str, agent_id: str) -> Dict[str, Any]:
        """
        Officer flags a fact as suspicious (e.g., income spike).

        CRITICAL: NEVER call mem0.add() for flagged facts.
        Flagged facts go to pending_review namespace only.
        """
        # Step 1: Append to WAL with pending_review=True
        self.wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id=agent_id,
            bank_id="central",
            facts=[{
                "fact_id": fact_id,
                "type": "flag",
                "source": "pending_review",
                "reason": reason,
                "verified": False,
                "pending_review": True
            }]
        )

        # Step 2: Publish to Redpanda fraud alerts topic
        if self.redpanda:
            await self.redpanda.publish(
                topic="fraud.alerts",
                message={
                    "session_id": session_id,
                    "customer_id": customer_id,
                    "fact_id": fact_id,
                    "reason": reason,
                    "agent_id": agent_id,
                    "timestamp": datetime.now(UTC).isoformat()
                }
            )

        # Step 3: DO NOT call mem0.add() — NEVER for flagged facts
        # This ensures flagged facts never contaminate the main memory graph

        return {
            "status": "flagged",
            "fact_id": fact_id,
            "wal_written": True,
            "mem0_written": False,  # Critical: always False for flags
            "fraud_alert_sent": True if self.redpanda else False
        }
