"""
Briefing builder module.

Builds structured pre-session briefing from customer memory.
Uses Redis cache with TTL=3600s for performance.
Falls back to mem0.search() on cache miss.
Includes conversational output via ConversationEngine.
"""

from typing import Dict, Any, Optional, List
import json
import os
import logging
from .conversation_engine import ConversationEngine

# Banking ID for composite user_id
BANK_ID = os.getenv("BANK_ID", "cooperative_bank_01")

logger = logging.getLogger(__name__)


class BriefingBuilder:
    """
    Build pre-session briefing for loan officer.
    
    Briefing includes: customer profile, session count, verified facts,
    recommended next step, and pending items.
    """

    def __init__(self, memory: Optional[Any] = None, redis_cache: Optional[Any] = None, health_checker: Optional[Any] = None, wal_logger: Optional[Any] = None):
        """
        Initialize briefing builder.

        Args:
            memory: mem0 Memory instance for searching facts
            redis_cache: Redis/aioredis instance for caching
            health_checker: MemoryHealthChecker instance for data quality assessment
            wal_logger: WALLogger instance for reading facts from WAL (primary source of truth)
        """
        self.memory = memory
        self.redis_cache = redis_cache
        self.health_checker = health_checker
        self.wal_logger = wal_logger

    async def build(self, customer_id: str) -> Dict[str, Any]:
        """
        Build briefing for customer.

        Steps:
        1. Check Redis cache (key: briefing:{customer_id})
        2. On hit: return cached briefing
        3. On miss: call mem0.search(), build briefing, cache it
        4. Return structured briefing dict

        Args:
            customer_id: Customer ID to build briefing for

        Returns:
            Briefing dict with required fields
        """
        # Step 1: Check Redis cache
        if self.redis_cache:
            cache_key = f"briefing:{customer_id}"
            cached = await self.redis_cache.get(cache_key)
            if cached:
                # Cache hit
                if isinstance(cached, bytes):
                    return json.loads(cached.decode())
                elif isinstance(cached, dict):
                    return cached
                elif isinstance(cached, str):
                    return json.loads(cached)

        # Step 2: Cache miss — build from memory
        briefing = await self._assemble_briefing(customer_id)

        # Step 3: Cache the result (TTL=3600s)
        if self.redis_cache:
            cache_key = f"briefing:{customer_id}"
            try:
                briefing_json = briefing if isinstance(briefing, str) else json.dumps(briefing)
                await self.redis_cache.set(cache_key, briefing_json, ex=3600)
            except Exception:
                # Cache write failed — continue without caching
                pass

        return briefing

    async def _assemble_briefing(self, customer_id: str) -> Dict[str, Any]:
        """
        Assemble briefing from WAL entries (source of truth).
        
        **OPTIMIZATION**: WAL is the authoritative source for all facts.
        Skip Mem0 layer (which requires LLM) - just read facts directly from WAL.
        This is faster and avoids RAM issues with Phi-4-Mini in memory.add().
        """
        memories = []

        # **CRITICAL FIX**: Read facts directly from WAL instead of Mem0
        # WAL contains all facts written during previous sessions (via /session/end)
        if hasattr(self, 'wal_logger') and self.wal_logger:
            try:
                # Get ALL entries for this customer (shipped + unshipped)
                all_entries = self.wal_logger.get_all_for_customer(customer_id)
                customer_facts = []

                for entry in all_entries:
                    facts = entry.get("facts", [])
                    customer_facts.extend(facts)
                
                # Convert to memory format
                for fact in customer_facts:
                    if isinstance(fact, dict):
                        memories.append({
                            "id": f"{customer_id}_{fact.get('type')}",
                            "content": f"{fact.get('type')}: {fact.get('value')}",
                            "type": fact.get("type"),
                            "value": fact.get("value"),
                            "verified": fact.get("verified", False)
                        })
                logger.info(f"Retrieved {len(memories)} facts from WAL for {customer_id}")
            except Exception as e:
                logger.debug(f"WAL retrieval failed: {e}")
                memories = []
        
        # Fallback to Mem0 if WAL fails (graceful degradation)
        if not memories and self.memory:
            try:
                composite_user_id = f"{BANK_ID}::{customer_id}"
                memories = self.memory.search(
                    query="customer income co-applicant property verification facts",
                    user_id=composite_user_id
                )
            except Exception as e:
                memories = []

        # Extract facts from memories
        verified_facts = []
        unverified_facts = []
        pending_review = []

        for mem in memories:
            # Parse content to extract type and value
            # Expected formats: "type: value" or just "content text"
            fact_type = "unknown"
            fact_value = mem.get("content", "")
            
            content_lower = mem.get("content", "").lower()
            if "income:" in content_lower or "salary:" in content_lower:
                fact_type = "income"
                # Extract value after colon
                parts = mem.get("content", "").split(":")
                if len(parts) > 1:
                    fact_value = parts[-1].strip()
            elif "co.applicant" in content_lower or "co-applicant" in content_lower or "sunita" in content_lower:
                fact_type = "co_applicant_name"
                parts = mem.get("content", "").split(":")
                fact_value = parts[-1].strip() if len(parts) > 1 else mem.get("content", "")
            elif "property" in content_lower or "location" in content_lower:
                fact_type = "property_location"
                parts = mem.get("content", "").split(":")
                fact_value = parts[-1].strip() if len(parts) > 1 else mem.get("content", "")
            elif "document" in content_lower or "payslip" in content_lower or "form 16" in content_lower:
                fact_type = "document_provided"
            
            fact = {
                "id": mem.get("id", ""),
                "type": fact_type,
                "value": fact_value,
                "content": mem.get("content", ""),
                "verified": mem.get("verified", False)
            }

            if mem.get("verified"):
                verified_facts.append(fact)
            else:
                unverified_facts.append(fact)

            if mem.get("requires_review"):
                pending_review.append(fact)

        # Determine recommended next step
        if not memories:
            recommended_next_step = "Collect customer information — no prior sessions found"
        elif pending_review:
            recommended_next_step = "Review pending items from last session"
        else:
            recommended_next_step = "Continue with loan application"

        # Build briefing
        briefing = {
            "customer_id": customer_id,
            "customer_name": self._extract_customer_name(memories),
            "session_count": len(memories) if len(memories) > 0 else 0,  # If we have facts, it's a returning customer (session_count >= 1)
            "verified_facts": verified_facts,
            "unverified_facts": unverified_facts,
            "pending_review": pending_review,
            "recommended_next_step": recommended_next_step,
            "flags": self._extract_flags(memories),
            "last_updated": self._get_timestamp()
        }

        # Add health checks if health checker is available (Phase 6)
        if self.health_checker:
            try:
                health = await self.health_checker.check(customer_id)
                briefing["flags"].extend(health.get("flags", []))
                briefing["is_healthy"] = health.get("is_healthy", True)
            except Exception:
                # Health check failed — continue with briefing
                pass

        # Add conversational output (experience layer)
        try:
            engine = ConversationEngine()
            all_facts = verified_facts + unverified_facts
            conversational = engine.build_conversational_briefing(
                customer_id=customer_id,
                customer_name=briefing.get("customer_name") or "there",
                facts=all_facts,
                flags=briefing["flags"],
                session_count=briefing["session_count"]
            )
            briefing.update(conversational)
        except Exception as e:
            # Conversation engine failed — add defaults
            briefing["greeting_message"] = "Welcome! How can I help you today?"
            briefing["context_summary"] = ""
            briefing["suggested_next"] = "Please let me know how I can assist."
            briefing["has_prior_context"] = False

        return briefing

    def _extract_customer_name(self, memories: List[Dict[str, Any]]) -> Optional[str]:
        """Extract customer name from memories if available."""
        for mem in memories:
            content = mem.get("content", "").lower()
            if "name:" in content or "customer:" in content:
                # Simple extraction — could be more sophisticated
                parts = mem.get("content", "").split(":")
                if len(parts) > 1:
                    return parts[-1].strip()
        return None

    def _extract_flags(self, memories: List[Dict[str, Any]]) -> List[str]:
        """Extract warning flags from memories."""
        flags = []
        for mem in memories:
            content = mem.get("content", "").lower()
            if "red flag" in content or "pending" in content or "review" in content:
                flags.append("review_required")
        return list(set(flags))  # Deduplicate

    def _get_timestamp(self) -> str:
        """Get current ISO timestamp."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
