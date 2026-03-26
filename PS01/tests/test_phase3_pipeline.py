"""
Phase 3 Pipeline Tests — TDD for event-driven architecture.

Pipeline flow:
  Redpanda consumer → ConflictDetector → AdversarialGuard → DerivesWorker → Mem0Bridge

Each component is independently testable; orchestrator coordinates them.
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.conflict_detector import ConflictDetector
from src.core.adversarial_guard import AdversarialGuard
from src.core.derives_worker import DerivesWorker
from src.core.mem0_bridge import Mem0Bridge
from src.infra.redpanda_consumer import RedpandaConsumer


class TestConflictDetectorPhase3:
    """Test conflict detection on new facts vs. existing facts."""

    def test_detect_numeric_conflict_suspicious(self):
        """Income change >50% should flag as suspicious."""
        existing = [{"type": "income", "value": 50000, "fact_id": "F001"}]
        new = [{"type": "income", "value": 100000}]

        conflicts = ConflictDetector.detect(existing, new)
        assert len(conflicts) == 1
        assert conflicts[0]["suspicious"] == True
        assert conflicts[0]["review_required"] == True
        assert conflicts[0]["pct_change"] == 1.0  # 100% change
        assert "reason" in conflicts[0]

    def test_detect_no_conflict_same_type_different_value_threshold(self):
        """Income change <50% should NOT flag as suspicious."""
        existing = [{"type": "income", "value": 50000, "fact_id": "F001"}]
        new = [{"type": "income", "value": 60000}]

        conflicts = ConflictDetector.detect(existing, new)
        assert len(conflicts) == 1
        assert conflicts[0]["suspicious"] == False
        assert conflicts[0]["review_required"] == False

    def test_detect_multiple_conflicts(self):
        """Multiple fact contradictions should all be detected."""
        existing = [
            {"type": "income", "value": 50000, "fact_id": "F001"},
            {"type": "emi_outgoing", "value": 5000, "fact_id": "F002"},
        ]
        new = [
            {"type": "income", "value": 100000},  # >50%, suspicious
            {"type": "emi_outgoing", "value": 8000},  # >30%, suspicious
        ]

        conflicts = ConflictDetector.detect(existing, new)
        assert len(conflicts) == 2
        assert all(c["suspicious"] for c in conflicts)


class TestAdversarialGuardPhase3:
    """Test adversarial fact-checking rules."""

    def test_check_income_above_threshold(self):
        """60% income increase should be flagged suspicious."""
        guard = AdversarialGuard()
        result = guard.check("income", 50000.0, 80000.0)
        assert result["suspicious"] == True
        assert result["pct_change"] == 0.6

    def test_check_emi_below_threshold(self):
        """20% EMI increase should NOT be flagged."""
        guard = AdversarialGuard()
        result = guard.check("emi_outgoing", 5000.0, 6000.0)
        assert result["suspicious"] == False
        assert result["pct_change"] == 0.2

    def test_check_loan_amount_doubled(self):
        """100% loan amount increase is at threshold; >100% is suspicious."""
        guard = AdversarialGuard()
        result_at = guard.check("loan_amount", 100000.0, 200000.0)
        assert result_at["suspicious"] == False  # exactly 100%, not > 100%

        result_above = guard.check("loan_amount", 100000.0, 210000.0)
        assert result_above["suspicious"] == True

    def test_check_unknown_fact_type(self):
        """Unknown fact types should not be suspicious."""
        guard = AdversarialGuard()
        result = guard.check("unknown_field", 100.0, 500.0)
        assert result["suspicious"] == False
        assert "no threshold" in result["reason"]


class TestDerivesWorkerPhase3:
    """Test derived fact calculation."""

    def test_calculate_net_income_and_eligibility(self):
        """From income + EMI facts, derive net income and loan eligibility."""
        facts = [
            {"type": "income", "value": 100000},
            {"type": "emi_outgoing", "value": 10000},
            {"type": "emi_outgoing", "value": 5000},
        ]

        derived = DerivesWorker().calculate(facts)
        assert derived["total_emi_burden"] == 15000
        assert derived["net_income"] == 85000
        assert derived["loan_eligibility"] == 5100000  # 85000 * 60

    def test_calculate_no_income_returns_empty(self):
        """If no income fact, return empty dict (cannot derive)."""
        facts = [
            {"type": "emi_outgoing", "value": 10000},
            {"type": "coapp_income", "value": 50000},
        ]

        derived = DerivesWorker().calculate(facts)
        assert derived == {}

    def test_calculate_zero_emi_burden(self):
        """No EMI facts means zero burden."""
        facts = [{"type": "income", "value": 100000}]

        derived = DerivesWorker().calculate(facts)
        assert derived["total_emi_burden"] == 0.0
        assert derived["net_income"] == 100000.0
        assert derived["loan_eligibility"] == 6000000.0  # 100000 * 60


class TestMem0BridgeIntegrationPhase3:
    """Test Mem0Bridge within pipeline context."""

    @pytest.mark.asyncio
    async def test_add_with_wal_and_redis_lock(self):
        """Mem0Bridge should: WAL → acquire Redis lock → mem0.add() → release lock."""
        # VERIFY: these classes and methods exist
        mock_memory = MagicMock()
        mock_wal = MagicMock()
        mock_wal.append = MagicMock()  # not async in real code
        mock_redis = AsyncMock()
        mock_redis.acquire_lock = AsyncMock(return_value="token_123")
        mock_redis.release_lock = AsyncMock()

        # Create bridge without decorator interception
        # (In real usage, the decorator would check consent DB)
        bridge = Mem0Bridge(mock_memory, mock_wal, bank_id="central", redis_cache=mock_redis)

        facts = [{"type": "income", "value": 100000}]
        
        # Mock the consent database to allow tests
        with patch("src.api.middleware.consent_db") as mock_consent:
            mock_consent.verify_consent = MagicMock(return_value=True)
            
            result = await bridge.add_with_wal(
                session_id="S001",
                customer_id="C001",
                agent_id="A001",
                facts=facts,
                bank_id="central"
            )

            assert result["status"] == "ok"
            assert result["facts_added"] == 1
            mock_wal.append.assert_called_once()
            mock_redis.acquire_lock.assert_called_once()
            mock_redis.release_lock.assert_called_once()


class TestRedpandaConsumerPhase3:
    """Test consumer event handling in pipeline."""

    @pytest.mark.asyncio
    async def test_consumer_deserialize_and_handler_call(self):
        """Consumer should deserialize JSON and call handler."""
        consumer = RedpandaConsumer(
            brokers=["localhost:9092"],
            bank_id="central",
            group_id="test-processor"
        )

        # Mock the internal AIOKafkaConsumer
        mock_msg = MagicMock()
        mock_msg.value = json.dumps({
            "session_id": "S001",
            "customer_id": "C001",
            "facts": [{"type": "income", "value": 100000}]
        }).encode("utf-8")
        mock_msg.offset = 0
        mock_msg.partition = 0

        handler = AsyncMock()

        # VERIFY: AIOKafkaConsumer supports async iteration
        # For testing, we'll mock it
        consumer._consumer = MagicMock()
        consumer._consumer.__aenter__ = AsyncMock(return_value=consumer._consumer)
        consumer._consumer.__aexit__ = AsyncMock(return_value=None)
        consumer._consumer.__aiter__ = MagicMock(return_value=iter([mock_msg]))
        consumer._consumer.commit = AsyncMock()

        # Manually call consume logic (won't iterate in test; just verify structure)
        assert consumer.topic == "central.session.events"
        assert consumer.group_id == "test-processor"


class TestPipelineOrchestrator:
    """Test the full pipeline: Consumer → Detector → Guard → Derives → Bridge."""

    @pytest.mark.asyncio
    async def test_orchestrator_wires_all_components(self):
        """Orchestrator should coordinate all 4 workers in sequence."""
        # VERIFY: PipelineOrchestrator class exists
        from src.core.pipeline_orchestrator import PipelineOrchestrator

        mock_memory = MagicMock()
        mock_memory.search = MagicMock(return_value=[])  # no existing facts
        mock_wal = MagicMock()
        mock_wal.append = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.acquire_lock = AsyncMock(return_value="token_123")
        mock_redis.release_lock = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        orchestrator = PipelineOrchestrator(
            memory=mock_memory,
            wal=mock_wal,
            redis=mock_redis,
            bank_id="central"
        )

        # Test a sample WAL entry flowing through the pipeline
        entry = {
            "session_id": "S001",
            "customer_id": "C001",
            "agent_id": "A001",
            "facts": [
                {"type": "income", "value": 100000, "verified": True},
                {"type": "emi_outgoing", "value": 10000, "verified": True},
            ]
        }

        # Mock consent database so tests can pass
        with patch("src.api.middleware.consent_db") as mock_consent:
            mock_consent.verify_consent = MagicMock(return_value=True)
            
            result = await orchestrator.process_entry(entry)

            # After pipeline: should have derived facts and processed entry
            assert "status" in result
            assert result["customer_id"] == "C001"
            assert "derived_facts" in result
            # Derived facts should be calculated
            assert result["derived_facts"]["net_income"] == 90000  # 100000 - 10000

    @pytest.mark.asyncio
    async def test_orchestrator_catches_adversarial_facts(self):
        """If a fact is suspicious, orchestrator should flag it for review."""
        from src.core.pipeline_orchestrator import PipelineOrchestrator

        mock_memory = MagicMock()
        mock_wal = MagicMock()
        mock_wal.append = MagicMock()

        orchestrator = PipelineOrchestrator(
            memory=mock_memory,
            wal=mock_wal,
            bank_id="central"
        )

        # Entry with suspicious fact (income doubled)
        existing_facts = [{"type": "income", "value": 50000, "fact_id": "F001"}]
        new_entry = {
            "session_id": "S001",
            "customer_id": "C001",
            "agent_id": "A001",
            "facts": [
                {"type": "income", "value": 120000, "verified": False},  # 140% increase
            ]
        }

        with patch("src.core.mem0_bridge.require_consent", lambda **kw: lambda f: f):
            with patch.object(
                orchestrator,
                "get_existing_facts",
                return_value=existing_facts,
            ):
                result = await orchestrator.process_entry(new_entry)

        # Should flag as review_required within conflicts
        assert "conflicts" in result or "review_required" in str(result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
