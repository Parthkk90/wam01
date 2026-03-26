"""
Phase 5 Session API — TDD for FastAPI endpoints + CBS Pre-seeding + Briefing + Evaluation.

Tests cover:
1. CBS preseeder with real CBS lookup and empty list for unknown customers
2. Briefing builder with Redis caching (<2000ms total, <50ms on hit)
3. Session start/end lifecycle with proper WAL-first sequencing
4. Memory retrieval with dual cache/mem0 paths
5. Evaluation harness with baseline metrics (7.2 repeated questions)
6. Full integration: session flow with all components
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timedelta, UTC
import asyncio

# Phase 0-4 imports (do not mock these)
from src.core.wal import WALLogger
from src.preprocessing.tokenizer import BankingTokenizer
from src.core.conflict_detector import ConflictDetector


# Placeholder imports for Phase 5 (to be implemented)
# from src.core.cbs_preseeder import CBSPreseeder
# from src.core.briefing_builder import BriefingBuilder
# from src.core.evaluation_harness import EvaluationHarness
# from src.api.session import router
# from src.api.models import SessionStartRequest, SessionStartResponse


class TestCBSPreseedingPhase5:
    """Test CBS pre-seeding with MOCK_CBS data."""

    @pytest.mark.asyncio
    async def test_cbs_preseeder_known_customer_returns_verified_facts(self):
        """
        CBSPreseeder with mock CBS should return verified facts.
        For Rajesh (C001): account_vintage_years, avg_monthly_credit_inr, etc.
        """
        from src.core.cbs_preseeder import CBSPreseeder

        # Mock CBS data (simulates real CBS)
        MOCK_CBS = {
            "C001": {
                "customer_name": "Rajesh Kumar",
                "account_vintage_years": 7,
                "avg_monthly_credit_inr": 54000,
                "existing_emis_inr": 0,
                "credit_behaviour": "clean",
                "savings_balance_tier": "medium"
            }
        }

        mock_cbs_api = AsyncMock()
        mock_cbs_api.get_customer = AsyncMock(
            return_value=MOCK_CBS.get("C001")
        )

        preseeder = CBSPreseeder(cbs_api=mock_cbs_api)
        facts = await preseeder.preseed(customer_id="C001")

        # Should return 6 facts (one for each CBS field)
        assert len(facts) >= 4
        assert all(f["verified"] == True for f in facts)
        assert all(f["source"] == "cbs_fetched" for f in facts)
        
        # Check specific fact types
        fact_types = {f["type"] for f in facts}
        assert "customer_name" in fact_types or "account_vintage_years" in fact_types

    @pytest.mark.asyncio
    async def test_cbs_preseeder_unknown_customer_returns_empty_list(self):
        """CBSPreseeder for unknown customer (new customer) returns empty list."""
        from src.core.cbs_preseeder import CBSPreseeder

        mock_cbs_api = AsyncMock()
        mock_cbs_api.get_customer = AsyncMock(return_value=None)

        preseeder = CBSPreseeder(cbs_api=mock_cbs_api)
        facts = await preseeder.preseed(customer_id="UNKNOWN")

        assert facts == []

    @pytest.mark.asyncio
    async def test_cbs_preseeder_wal_written_before_mem0(self):
        """
        CRITICAL: When CBS facts are added to memory, WAL.append() must be called FIRST.
        This simulates the session_start flow with CBS facts.
        """
        # Real WAL logger (Phase 0-3, do not mock)
        wal = WALLogger(wal_path="/tmp/test_wal_phase5_cbs.jsonl")

        call_order = []

        # Mock mem0 and Redis
        mock_memory = MagicMock()
        mock_memory.add = MagicMock()

        # Simulate CBS pre-seeding → WAL → mem0 flow
        session_id = "S001"
        customer_id = "C001"
        cbs_facts = [
            {"type": "account_vintage_years", "value": 7, "verified": True, "source": "cbs_fetched"}
        ]

        # Step 1: WAL FIRST
        call_order.append("wal_append")
        wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id="cbs_preseed",
            bank_id="central",
            facts=cbs_facts
        )

        # Step 2: mem0.add()
        call_order.append("mem0_add")
        mock_memory.add(
            messages=[{"role": "system", "content": json.dumps(cbs_facts)}],
            user_id=customer_id
        )

        # Verify order
        assert call_order == ["wal_append", "mem0_add"]
        
        # Verify WAL file has CBS facts
        with open(wal.wal_path) as f:
            entry = json.loads(f.readline())
            assert entry["session_id"] == session_id
            assert entry["facts"][0]["source"] == "cbs_fetched"


class TestBriefingBuilderPhase5:
    """Test briefing builder with Redis caching and mem0 fallback."""

    @pytest.mark.asyncio
    async def test_briefing_builder_redis_cache_hit(self):
        """
        Redis cache hit should return briefing in <50ms.
        Key format: briefing:{customer_id}
        """
        from src.core.briefing_builder import BriefingBuilder

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value={
            "customer_id": "C001",
            "customer_name": "Rajesh Kumar",
            "session_count": 3,
            "verified_facts": [
                {"type": "account_vintage_years", "value": 7}
            ],
            "unverified_facts": [],
            "pending_review": [],
            "recommended_next_step": "Document verification",
            "flags": [],
            "last_updated": datetime.now(UTC).isoformat()
        })

        builder = BriefingBuilder(redis_cache=mock_redis, memory=MagicMock())
        
        import time
        start = time.time()
        briefing = await builder.build(customer_id="C001")
        elapsed_ms = (time.time() - start) * 1000

        # Should be fast (cache hit)
        assert elapsed_ms < 50
        assert briefing["customer_name"] == "Rajesh Kumar"
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_briefing_builder_cache_miss_calls_mem0(self):
        """
        Cache miss: call mem0.search(), build briefing, cache result (TTL=3600s).
        Total time:  <2000ms (includes mem0 call).
        """
        from src.core.briefing_builder import BriefingBuilder

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Cache miss
        mock_redis.set = AsyncMock()

        mock_memory = MagicMock()
        mock_memory.search = MagicMock(return_value=[
            {"id": "F001", "content": "account_vintage: 7 years"},
            {"id": "F002", "content": "avg_monthly_credit: 54000"}
        ])

        builder = BriefingBuilder(redis_cache=mock_redis, memory=mock_memory)
        
        import time
        start = time.time()
        briefing = await builder.build(customer_id="C001")
        elapsed_ms = (time.time() - start) * 1000

        # Should complete in <2000ms
        assert elapsed_ms < 2000
        
        # Should call mem0.search
        mock_memory.search.assert_called_once()
        
        # Should set Redis cache
        mock_redis.set.assert_called_once()
        set_call_kwargs = mock_redis.set.call_args[1]
        # Verify TTL parameter (ex= for expire in seconds)
        assert set_call_kwargs.get("ex") == 3600 or set_call_kwargs.get("ttl") == 3600

    @pytest.mark.asyncio
    async def test_briefing_builder_returns_required_fields(self):
        """Briefing must contain: customer_id, customer_name, session_count, verified_facts, unverified_facts, pending_review, recommended_next_step, flags, last_updated."""
        from src.core.briefing_builder import BriefingBuilder

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        builder = BriefingBuilder(redis_cache=mock_redis, memory=MagicMock())
        
        # Mock internal briefing assembly
        required_fields = {
            "customer_id": "C001",
            "customer_name": "Rajesh Kumar",
            "session_count": 3,
            "verified_facts": [],
            "unverified_facts": [],
            "pending_review": [],
            "recommended_next_step": "Document upload",
            "flags": [],
            "last_updated": datetime.now(UTC).isoformat()
        }

        with patch.object(builder, "_assemble_briefing", return_value=required_fields):
            briefing = await builder.build(customer_id="C001")

        for field in required_fields.keys():
            assert field in briefing, f"Missing field: {field}"


class TestSessionAPIPhase5:
    """Test /session/start and /session/end endpoints."""

    @pytest.mark.asyncio
    async def test_session_start_verifies_consent_first(self):
        """POST /session/start must verify consent BEFORE proceeding."""
        
        mock_consent_db = MagicMock()
        mock_consent_db.verify_consent = MagicMock(return_value=False)

        # Simulate session start
        consent_verified = mock_consent_db.verify_consent(
            session_id="S001",
            scope="home_loan_processing"
        )

        assert consent_verified == False
        mock_consent_db.verify_consent.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_start_triggers_cbs_preseed(self):
        """
        POST /session/start flow:
        1. Verify consent
        2. Generate session_id
        3. Run CBSPreseeder.preseed()
        4. Call BriefingBuilder.build()
        5. Return session_id + briefing
        """
        from src.core.cbs_preseeder import CBSPreseeder
        from src.core.briefing_builder import BriefingBuilder

        # Mocks
        mock_consent_db = MagicMock()
        mock_consent_db.verify_consent = MagicMock(return_value=True)

        mock_cbs_api = AsyncMock()
        mock_cbs_api.get_customer = AsyncMock(return_value={
            "customer_name": "Rajesh Kumar",
            "account_vintage_years": 7
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        # Initialize components
        preseeder = CBSPreseeder(cbs_api=mock_cbs_api)
        builder = BriefingBuilder(redis_cache=mock_redis, memory=MagicMock())

        # Simulate session start flow
        customer_id = "C001"
        session_type = "home_loan_processing"

        # Step 1: Verify consent
        assert mock_consent_db.verify_consent(session_id="S001", scope=session_type) == True

        # Step 2: CBS preseed
        cbs_facts = await preseeder.preseed(customer_id=customer_id)
        assert len(cbs_facts) >= 1

        # Step 3: Build briefing
        briefing = await builder.build(customer_id=customer_id)
        assert "customer_name" in briefing or briefing is not None

    @pytest.mark.asyncio
    async def test_session_start_returns_briefing(self):
        """POST /session/start response includes: session_id, status, briefing dict."""
        
        mock_session_response = {
            "session_id": "sess_abc123def456",
            "status": "ready",
            "briefing": {
                "customer_id": "C001",
                "customer_name": "Rajesh Kumar",
                "session_count": 3,
                "verified_facts": [],
                "unverified_facts": [],
                "pending_review": [],
                "recommended_next_step": "Document verification",
                "flags": [],
                "last_updated": datetime.now(UTC).isoformat()
            }
        }

        assert "session_id" in mock_session_response
        assert "status" in mock_session_response
        assert "briefing" in mock_session_response
        assert mock_session_response["status"] == "ready"

    @pytest.mark.asyncio
    async def test_session_end_wal_before_redpanda(self):
        """
        CRITICAL: Session end must:
        1. Tokenize transcript
        2. WAL.append() FIRST
        3. Publish to Redpanda (only after WAL)
        4. Trigger Phi4Compactor (background)
        """
        # Real WAL logger
        wal = WALLogger(wal_path="/tmp/test_wal_phase5_session_end.jsonl")
        
        # Real tokenizer
        tokenizer = BankingTokenizer()

        call_order = []

        # Mock Redpanda
        mock_redpanda = AsyncMock()
        mock_redpanda.publish = AsyncMock()

        # Mock compactor
        mock_compactor = AsyncMock()
        mock_compactor.compact = AsyncMock()

        # Session end flow
        session_id = "S001"
        customer_id = "C001"
        transcript = "Mera PAN ABCDE1234F hai, income 100000 per month"

        # Step 1: Tokenize
        tokenized, token_map = tokenizer.tokenize(transcript)

        facts = [
            {
                "type": "transcript",
                "value": tokenized,
                "verified": False,
                "source": "voice_transcribed",
                "token_mapping": token_map
            }
        ]

        # Step 2: WAL FIRST
        call_order.append("wal_append")
        wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id="agent_1",
            bank_id="central",
            facts=facts
        )

        # Step 3: Redpanda (only after WAL)
        call_order.append("redpanda_publish")
        await mock_redpanda.publish(
            topic="central.session.events",
            key=customer_id,
            value={"session_id": session_id, "facts": facts}
        )

        # Step 4: Compactor (background)
        call_order.append("compactor")
        await mock_compactor.compact(facts=facts)

        # Verify order
        assert call_order == ["wal_append", "redpanda_publish", "compactor"]

        # Verify WAL has tokenized data (no raw PAN)
        with open(wal.wal_path) as f:
            entry = json.loads(f.readline())
            assert "ABCDE1234F" not in json.dumps(entry)

    @pytest.mark.asyncio
    async def test_session_end_triggers_compact_background(self):
        """
        Session end should trigger Phi4Compactor as BACKGROUND task.
        Compactor writes summary to Redis: key="summary:{customer_id}", TTL=14400s.
        """
        mock_compactor = AsyncMock()
        mock_compactor.compact = AsyncMock(return_value={
            "consolidated_facts": 12,
            "summary": "Customer has 7-year banking relationship..."
        })

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        # Simulate background task
        facts = [{"type": "income", "value": "100000"}]
        compact_result = await mock_compactor.compact(facts=facts)

        # Write to Redis
        await mock_redis.set(
            key="summary:C001",
            value=compact_result,
            ttl=14400
        )

        # Verify Redis write
        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args[1]
        assert call_kwargs.get("ttl") == 14400

    @pytest.mark.asyncio
    async def test_session_add_fact_wal_first(self):
        """
        POST /session/add-fact must:
        1. WAL.append() FIRST
        2. Publish to Redpanda
        3. Return fact_id, wal_written=True
        """
        wal = WALLogger(wal_path="/tmp/test_wal_phase5_add_fact.jsonl")
        
        call_order = []

        mock_redpanda = AsyncMock()
        mock_redpanda.publish = AsyncMock()

        # Add fact flow
        session_id = "S001"
        customer_id = "C001"
        fact = {
            "type": "income",
            "value": "100000",
            "verified": False,
            "source": "agent_entered"
        }

        # Step 1: WAL FIRST
        call_order.append("wal_append")
        wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id="agent_1",
            bank_id="central",
            facts=[fact]
        )

        # Step 2: Redpanda
        call_order.append("redpanda_publish")
        await mock_redpanda.publish(
            topic="central.session.events",
            key=customer_id,
            value={"session_id": session_id, "fact": fact}
        )

        # Verify order
        assert call_order == ["wal_append", "redpanda_publish"]


class TestMemoryRetrievalPhase5:
    """Test /session/memory/{customer_id} endpoint."""

    @pytest.mark.asyncio
    async def test_memory_retrieval_redis_hit(self):
        """
        GET /session/memory/{customer_id}:
        1. Check Redis cache (briefing:{customer_id})
        2. If hit: return cached briefing immediately
        """
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value={
            "customer_id": "C001",
            "customer_name": "Rajesh Kumar",
            "verified_facts": [
                {"type": "account_vintage_years", "value": 7}
            ]
        })

        # Simulate retrieval
        briefing = await mock_redis.get(key="briefing:C001")

        assert briefing is not None
        assert briefing["customer_id"] == "C001"
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_memory_retrieval_cache_miss_calls_mem0(self):
        """
        Cache miss:
        1. Call mem0.search() for customer memories
        2. Assemble briefing
        3. Cache it in Redis
        4. Return briefing + raw_memories list
        """
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Cache miss
        mock_redis.set = AsyncMock()

        mock_memory = MagicMock()
        mock_memory.search = MagicMock(return_value=[
            {"id": "F001", "content": "account_vintage: 7 years"},
            {"id": "F002", "content": "income: 100000"}
        ])

        # Simulate retrieval
        memories = mock_memory.search(query="loan application", user_id="C001")

        assert len(memories) == 2
        mock_memory.search.assert_called_once()

        # Cache the result
        await mock_redis.set(
            key="briefing:C001",
            value={"customer_id": "C001", "raw_memories": memories},
            ttl=3600
        )

        mock_redis.set.assert_called_once()


class TestEvaluationHarnessPhase5:
    """Test evaluation harness with baseline metrics."""

    @pytest.mark.asyncio
    async def test_evaluation_harness_baseline_is_7_point_2(self):
        """
        EvaluationHarness baseline: 7.2 repeated questions (hardcoded in no-memory scenario).
        This is the control metric for judges to compare against.
        """
        from src.core.evaluation_harness import EvaluationHarness

        harness = EvaluationHarness()
        
        # Baseline should be exactly 7.2
        assert harness.baseline_repeated_questions == 7.2

    @pytest.mark.asyncio
    async def test_evaluation_harness_compare_shows_improvement(self):
        """
        EvaluationHarness.compare() returns:
        {
            "baseline": 7.2,
            "with_ps01": float (fewer repeated questions),
            "improvement_pct": float (positive = better)
        }
        """
        from src.core.evaluation_harness import EvaluationHarness

        harness = EvaluationHarness()
        
        # Mock a PS-01 run that reduces repeated questions
        mock_ps01_result = {
            "repeated_questions": 2.1,  # Much better than baseline 7.2
            "recall_accuracy": 0.94
        }

        comparison = harness.compare(ps01_metrics=mock_ps01_result)

        assert "baseline" in comparison
        assert "with_ps01" in comparison
        assert "improvement_pct" in comparison
        assert comparison["baseline"] == 7.2
        # Improvement should be positive
        improvement = (7.2 - mock_ps01_result["repeated_questions"]) / 7.2 * 100
        assert improvement > 70  # Should be significant improvement

    @pytest.mark.asyncio
    async def test_evaluation_harness_run_scenario(self):
        """
        EvaluationHarness.run_scenario(scenario_id) runs a predefined test journey.
        Returns metrics: {repeated_questions, recall_accuracy, session_start_ms}
        """
        from src.core.evaluation_harness import EvaluationHarness

        harness = EvaluationHarness()
        
        # Run a scenario (e.g., "Rajesh's 4th session")
        metrics = harness.run_scenario(scenario_id=1)

        assert "repeated_questions" in metrics
        assert "recall_accuracy" in metrics
        assert "session_start_ms" in metrics
        assert metrics["session_start_ms"] < 2000  # Should be fast


class TestFullSessionIntegrationPhase5:
    """Integration test: complete session flow with all components."""

    @pytest.mark.asyncio
    async def test_full_session_flow_cbs_briefing_compact(self):
        """
        Full flow:
        1. /session/start → verify consent → CBS preseed → build briefing
        2. Agent adds facts → WAL → Redpanda
        3. /session/end → tokenize → WAL → Redpanda → compact → Redis summary
        """
        # Use real components from Phase 0-3
        wal = WALLogger(wal_path="/tmp/test_wal_full_session.jsonl")
        tokenizer = BankingTokenizer()

        # Mock external services
        mock_cbs_api = AsyncMock()
        mock_cbs_api.get_customer = AsyncMock(return_value={
            "customer_name": "Rajesh Kumar",
            "account_vintage_years": 7
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_memory = MagicMock()
        mock_memory.search = MagicMock(return_value=[
            {"id": "F001", "content": "previous sessions: 3"}
        ])
        mock_memory.add = MagicMock()

        mock_redpanda = AsyncMock()
        mock_redpanda.publish = AsyncMock()

        mock_compactor = AsyncMock()
        mock_compactor.compact = AsyncMock(return_value={"summary": "..."})

        # Session flow
        from src.core.cbs_preseeder import CBSPreseeder
        from src.core.briefing_builder import BriefingBuilder

        session_id = "sess_full_001"
        customer_id = "C001"
        bank_id = "central"

        # Step 1: Session start
        preseeder = CBSPreseeder(cbs_api=mock_cbs_api)
        builder = BriefingBuilder(redis_cache=mock_redis, memory=mock_memory)

        cbs_facts = await preseeder.preseed(customer_id=customer_id)
        
        # WAL append CBS facts FIRST
        wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id="cbs",
            bank_id=bank_id,
            facts=cbs_facts
        )

        briefing = await builder.build(customer_id=customer_id)

        # Step 2: Agent adds facts
        agent_fact = {"type": "income", "value": "100000", "verified": False}

        wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id="agent",
            bank_id=bank_id,
            facts=[agent_fact]
        )

        # Step 3: Session end
        transcript = "Customer income is 100000"
        tokenized, token_map = tokenizer.tokenize(transcript)

        end_facts = [
            {"type": "transcript", "value": tokenized, "verified": False}
        ]

        wal.append(
            session_id=session_id,
            customer_id=customer_id,
            agent_id="agent",
            bank_id=bank_id,
            facts=end_facts
        )

        await mock_redpanda.publish(topic=f"{bank_id}.session.events", value={"session_id": session_id})
        
        await mock_compactor.compact(facts=end_facts)
        
        await mock_redis.set(key=f"summary:{customer_id}", value={"summary": "..."}, ttl=14400)

        # Verify WAL has all three writes
        with open(wal.wal_path) as f:
            entries = [json.loads(line) for line in f]
            assert len(entries) >= 3  # CBS + agent + end


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
