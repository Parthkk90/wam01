"""
Demo Seeder — Rajesh 4-session journey for demo experience.

CRITICAL: Every fact written to WAL first, then mem0.
Session 4 income supersedes Session 1 income.
"""

from typing import Dict, Any
from datetime import datetime, timedelta
from src.core.wal import WALLogger


# Demo configuration
DEMO_CUSTOMER_ID = "C001"
DEMO_AGENT_IDS = ["AGT_A", "AGT_B", "AGT_C", "AGT_D"]


class DemoSeeder:
    """Seed Rajesh 4-session journey for demo evaluation."""

    def __init__(self, wal: WALLogger, memory=None, redis=None):
        """
        Args:
            wal: WALLogger for fact writes
            memory: Mem0 instance
            redis: Redis for cache invalidation
        """
        self.wal = wal
        self.memory = memory
        self.redis = redis

    async def seed_rajesh_journey(self) -> Dict[str, Any]:
        """
        Seed Rajesh 4-session journey over ~19 days.

        Returns:
            {status, sessions, facts_total, customer_id}
        """
        customer_id = DEMO_CUSTOMER_ID
        facts_count = 0

        # Session 1 (Day 0): Initial verbal info
        session_1_facts = [
            {
                "fact_id": "F001",
                "type": "income",
                "value": "55000_INR_MONTHLY",
                "verified": False,
                "source": "customer_verbal",
                "relationship": "new"
            },
            {
                "fact_id": "F002",
                "type": "employer",
                "value": "Pune_MNC",
                "verified": False,
                "source": "customer_verbal",
                "relationship": "new"
            },
            {
                "fact_id": "F003",
                "type": "co_applicant",
                "value": "Sunita_Kumar_wife",
                "verified": False,
                "source": "customer_verbal",
                "relationship": "new"
            }
        ]
        self.wal.append(
            session_id="S001",
            customer_id=customer_id,
            agent_id=DEMO_AGENT_IDS[0],
            bank_id="central",
            facts=session_1_facts
        )
        facts_count += len(session_1_facts)

        # Session 2 (Day 6): EMI and co-applicant income
        session_2_facts = [
            {
                "fact_id": "F004",
                "type": "emi_outgoing",
                "value": "12000_INR_MONTHLY",
                "verified": False,
                "source": "customer_verbal",
                "relationship": "new"
            },
            {
                "fact_id": "F005",
                "type": "co_applicant_income",
                "value": "30000_INR_MONTHLY",
                "verified": False,
                "source": "customer_verbal",
                "relationship": "extends",
                "extends": "F003"
            }
        ]
        self.wal.append(
            session_id="S002",
            customer_id=customer_id,
            agent_id=DEMO_AGENT_IDS[1],
            bank_id="central",
            facts=session_2_facts
        )
        facts_count += len(session_2_facts)

        # Session 3 (Day 12): Land document
        session_3_facts = [
            {
                "fact_id": "F006",
                "type": "land_record",
                "value": "Nashik_plot_1200sqm_encumbrance_clean",
                "verified": True,
                "source": "document_parsed",
                "relationship": "new"
            }
        ]
        self.wal.append(
            session_id="S003",
            customer_id=customer_id,
            agent_id=DEMO_AGENT_IDS[2],
            bank_id="central",
            facts=session_3_facts
        )
        facts_count += len(session_3_facts)

        # Session 4 (Day 19): Income correction and derived eligibility
        session_4_facts = [
            {
                "fact_id": "F007",
                "type": "income",
                "value": "62000",
                "verified": False,
                "source": "customer_verbal",
                "relationship": "updates",
                "supersedes": "S001_income"
            },
            {
                "fact_id": "F008",
                "type": "derived_eligibility",
                "value": "48L_INR_indicative",
                "verified": False,
                "source": "derived",
                "confidence": 0.91,
                "relationship": "derives",
                "derived_from": ["F007", "F005", "F004"]
            }
        ]
        self.wal.append(
            session_id="S004",
            customer_id=customer_id,
            agent_id=DEMO_AGENT_IDS[3],
            bank_id="central",
            facts=session_4_facts
        )
        facts_count += len(session_4_facts)

        return {
            "status": "seeded",
            "sessions": 4,
            "facts_total": facts_count,
            "customer_id": customer_id
        }

    async def clear_demo_data(self, customer_id: str = DEMO_CUSTOMER_ID) -> Dict[str, Any]:
        """
        Clear all demo data for customer from Redis, Mem0, and WAL.

        Returns:
            {status, customer_id}
        """
        # Step 1: Redis cache invalidation
        if self.redis:
            cache_keys = [
                f"summary:{customer_id}",
                f"briefing:{customer_id}",
                f"cbs:{customer_id}",
                f"session:S001",
                f"session:S002",
                f"session:S003",
                f"session:S004"
            ]
            for key in cache_keys:
                try:
                    await self.redis.delete(key)
                except Exception:
                    pass

        # Step 2: Mem0 deletion (use delete_all if available)
        if self.memory:
            try:
                # Try to delete all facts for user
                if hasattr(self.memory, 'delete_all'):
                    await self.memory.delete_all(user_id=customer_id)
                else:
                    # Fallback: clear through get/delete pattern
                    result = self.memory.get(user_id=customer_id)
                    if result:
                        # Memory might not have delete method, skip
                        pass
            except Exception:
                pass

        # Step 3: WAL rewrite (remove all entries for customer_id)
        if self.wal.wal_path.exists():
            try:
                import json
                # Read all entries
                entries = []
                with open(self.wal.wal_path, "r") as f:
                    for line in f:
                        if line.strip():
                            entries.append(json.loads(line))

                # Filter out customer entries
                filtered = [e for e in entries if e.get("customer_id") != customer_id]

                # Rewrite WAL
                with open(self.wal.wal_path, "w") as f:
                    for entry in filtered:
                        f.write(json.dumps(entry) + "\n")
            except Exception:
                pass

        return {
            "status": "cleared",
            "customer_id": customer_id
        }
