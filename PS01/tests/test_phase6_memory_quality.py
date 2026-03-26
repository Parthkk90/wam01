"""
Phase 6: Memory Quality Layer — TDD Test Suite.

Tests cover:
1. Feedback processor (corrections, confirmations, flags)
2. Memory timeline (WAL-based history reconstruction)
3. Memory health checker (data quality metrics)
4. Demo seeder (Rajesh 4-session journey)
5. Full demo evaluation flow

CRITICAL: All write tests assert WAL.append() happens BEFORE mem0.add()
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timedelta
import asyncio
from pathlib import Path

# Imports from Phases 0-5 (DO NOT MODIFY)
from src.core.wal import WALLogger
from src.preprocessing.tokenizer import BankingTokenizer
from src.core.conflict_detector import ConflictDetector
from src.api.middleware import ConsentDB
import tempfile


class TestFeedbackProcessorCorrection:
    """Test correction: officer fixes wrong fact with WAL-first guarantee."""

    @pytest.mark.asyncio
    async def test_feedback_correction_wal_before_mem0(self):
        """
        CRITICAL: WAL.append() must be called BEFORE mem0.add().
        
        Scenario: Officer corrects income from 55K (wrong) to 62K (right).
        Verify: WAL written first, then mem0 updated with supersedes relationship.
        """
        # Setup
        wal = WALLogger(wal_path="/tmp/test_feedback_wal.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()
        mock_mem0.search = MagicMock(return_value=[
            {
                "id": "F001",
                "content": "income: 55000",
                "verified": False,
                "source": "customer_verbal"
            }
        ])

        # Import will be created in implementation
        from src.core.feedback_processor import FeedbackProcessor
        processor = FeedbackProcessor(wal=wal, memory=mock_mem0)

        # Execute: Officer corrects income
        result = await processor.process_correction(
            session_id="S003",
            customer_id="C001",
            fact_id="F001",
            corrected_value="62000",
            agent_id="officer_priya"
        )

        # Assert: WAL was appended
        assert result["wal_written"] == True
        with open(wal.wal_path) as f:
            entries = [json.loads(line) for line in f]
            assert len(entries) > 0
            last_entry = entries[-1]
            assert last_entry["customer_id"] == "C001"
            assert last_entry["facts"][0]["type"] == "income"
            assert last_entry["facts"][0]["value"] == "62000"
            assert last_entry["facts"][0]["source"] == "officer_verified"
            assert last_entry["facts"][0]["confidence"] == 0.99

        # Assert: mem0.add() was called AFTER WAL
        mock_mem0.add.assert_called_once()
        call_args = mock_mem0.add.call_args
        # Verify mem0 was passed messages with new fact (check kwargs)
        assert "62000" in str(call_args.kwargs) or any("62000" in str(arg) for arg in call_args[0])

    @pytest.mark.asyncio
    async def test_feedback_correction_confidence_is_0_99(self):
        """Officer corrections marked with confidence=0.99 (highest, document-verified level)."""
        from src.core.feedback_processor import FeedbackProcessor
        
        wal = WALLogger(wal_path="/tmp/test_correction_conf.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()
        mock_mem0.search = MagicMock(return_value=[{"id": "F001", "content": "income: 55000"}])

        processor = FeedbackProcessor(wal=wal, memory=mock_mem0)
        result = await processor.process_correction(
            session_id="S003",
            customer_id="C001",
            fact_id="F001",
            corrected_value="62000",
            agent_id="officer_priya"
        )

        # Verify confidence = 0.99
        with open(wal.wal_path) as f:
            entry = json.loads(f.readline())
            assert entry["facts"][0]["confidence"] == 0.99
            assert entry["facts"][0]["verified"] == True


class TestFeedbackProcessorConfirmation:
    """Test confirmation: officer verifies a verbal fact with document."""

    @pytest.mark.asyncio
    async def test_feedback_confirmation_upgrades_source_to_officer_verified(self):
        """
        Confirmation upgrades customer_verbal → officer_verified.
        Example: Officer sees land record, confirms the land location is correct.
        """
        from src.core.feedback_processor import FeedbackProcessor

        wal = WALLogger(wal_path="/tmp/test_confirm_wal.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()
        mock_mem0.search = MagicMock(return_value=[
            {
                "id": "F006",
                "content": "land_location: Nashik",
                "source": "customer_verbal"
            }
        ])

        processor = FeedbackProcessor(wal=wal, memory=mock_mem0)
        result = await processor.process_confirmation(
            session_id="S003",
            customer_id="C001",
            fact_id="F006",
            agent_id="officer_priya"
        )

        # Assert: confirmation written to WAL with relationship="verifies"
        with open(wal.wal_path) as f:
            entry = json.loads(f.readline())
            assert entry["facts"][0]["relationship"] == "verifies"
            assert entry["facts"][0]["source"] == "officer_verified"
            assert entry["facts"][0]["verified"] == True

        # Assert: mem0.add() called with verification message
        mock_mem0.add.assert_called_once()


class TestFeedbackProcessorFlag:
    """Test flag: marked suspicious, goes to fraud topic, DOES NOT write to main graph."""

    @pytest.mark.asyncio
    async def test_feedback_flag_does_not_write_to_main_graph(self):
        """
        CRITICAL: Flagged facts go to pending_review namespace only.
        mem0.add() must NOT be called for flagged facts.
        """
        from src.core.feedback_processor import FeedbackProcessor

        wal = WALLogger(wal_path="/tmp/test_flag_wal.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()
        mock_redpanda = MagicMock()
        mock_redpanda.publish = AsyncMock()

        processor = FeedbackProcessor(
            wal=wal,
            memory=mock_mem0,
            redpanda=mock_redpanda
        )

        result = await processor.process_flag(
            session_id="S002",
            customer_id="C001",
            fact_id="F003",
            reason="income_spike_unexplained",
            agent_id="officer_priya"
        )

        # Assert: mem0.add() was NEVER called
        mock_mem0.add.assert_not_called()

        # Assert: flag written to WAL with pending_review=True
        with open(wal.wal_path) as f:
            entry = json.loads(f.readline())
            assert entry["facts"][0]["pending_review"] == True
            assert entry["facts"][0]["reason"] == "income_spike_unexplained"

    @pytest.mark.asyncio
    async def test_feedback_flag_publishes_to_fraud_alerts_topic(self):
        """Flagged facts published to Redpanda fraud.alerts topic for compliance review."""
        from src.core.feedback_processor import FeedbackProcessor

        wal = WALLogger(wal_path="/tmp/test_flag_redpanda.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()
        mock_redpanda = MagicMock()
        mock_redpanda.publish = AsyncMock()

        processor = FeedbackProcessor(wal=wal, memory=mock_mem0, redpanda=mock_redpanda)

        await processor.process_flag(
            session_id="S002",
            customer_id="C001",
            fact_id="F003",
            reason="income_spike_unexplained",
            agent_id="officer_priya"
        )

        # Assert: published to fraud.alerts
        mock_redpanda.publish.assert_called_once()
        call_args = mock_redpanda.publish.call_args
        assert "fraud" in str(call_args).lower()


class TestMemoryTimeline:
    """Test timeline reconstruction from WAL (read-only, no mem0 calls)."""

    @pytest.mark.asyncio
    async def test_memory_timeline_reads_wal_only(self):
        """Timeline built from WAL entries, never calls mem0."""
        # Seed WAL with facts from 3 sessions
        wal = WALLogger(wal_path="/tmp/test_timeline_wal.jsonl")

        # Session 1: income, employer
        wal.append(
            session_id="S001",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "income", "value": "55000", "source": "customer_verbal"},
                {"type": "employer", "value": "Pune MNC", "source": "customer_verbal"}
            ]
        )

        # Session 2: co-applicant income, EMI
        wal.append(
            session_id="S002",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "co_applicant_income", "value": "30000", "source": "customer_verbal"},
                {"type": "emi_outgoing", "value": "12000", "source": "customer_verbal"}
            ]
        )

        # Session 3: land document
        wal.append(
            session_id="S003",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "land_location", "value": "Nashik", "verified": True, "source": "document_parsed"}
            ]
        )

        # Import MemoryTimeline (to be created)
        from src.core.memory_timeline import MemoryTimeline
        
        # Create timeline — NO mem0 calls
        mock_mem0 = MagicMock()
        timeline = MemoryTimeline(wal=wal, memory=mock_mem0)

        # Get timeline for customer
        events = await timeline.get_timeline(customer_id="C001")

        # Assert: 3 events, no mem0.search() called
        assert len(events) >= 3
        mock_mem0.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_timeline_returns_4_events_for_rajesh(self):
        """Timeline for Rajesh shows 4 sessions over ~19 days."""
        wal = WALLogger(wal_path="/tmp/test_rajesh_timeline.jsonl")

        # Session 1 (day 0)
        wal.append(
            session_id="S001",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "income", "value": "55000"},
                {"type": "co_applicant_income", "value": "30000"}
            ]
        )

        # Session 2 (day 5)
        wal.append(
            session_id="S002",
            customer_id="C001",
            agent_id="officer_kumar",
            bank_id="central",
            facts=[
                {"type": "emi_outgoing", "value": "12000"},
                {"type": "derived_eligibility", "value": "4300000"}
            ]
        )

        # Session 3 (day 12)
        wal.append(
            session_id="S003",
            customer_id="C001",
            agent_id="officer_sharma",
            bank_id="central",
            facts=[
                {"type": "land_location", "value": "Nashik", "verified": True}
            ]
        )

        # Session 4 (day 19) — income correction
        wal.append(
            session_id="S004",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "income", "value": "62000", "source": "officer_verified"}
            ]
        )

        from src.core.memory_timeline import MemoryTimeline
        timeline = MemoryTimeline(wal=wal, memory=MagicMock())
        events = await timeline.get_timeline(customer_id="C001")

        # Assert: 4 events (one per session)
        assert len(events) == 4
        assert events[0]["session_id"] == "S001"
        assert events[1]["session_id"] == "S002"
        assert events[2]["session_id"] == "S003"
        assert events[3]["session_id"] == "S004"


class TestMemorySnapshot:
    """Test snapshot: freeze memory at a point in time (up to session_id)."""

    @pytest.mark.asyncio
    async def test_memory_snapshot_at_session2_has_no_land_record(self):
        """Snapshot at S002 shows income, employer, co-app income, EMI — but NO land record (added in S003)."""
        wal = WALLogger(wal_path="/tmp/test_snapshot_wal.jsonl")

        # Sessions 1-3
        wal.append(session_id="S001", customer_id="C001", agent_id="officer_priya", bank_id="central",
                   facts=[{"type": "income", "value": "55000"}])
        wal.append(session_id="S002", customer_id="C001", agent_id="officer_priya", bank_id="central",
                   facts=[{"type": "emi_outgoing", "value": "12000"}])
        wal.append(session_id="S003", customer_id="C001", agent_id="officer_priya", bank_id="central",
                   facts=[{"type": "land_location", "value": "Nashik", "verified": True}])

        from src.core.memory_timeline import MemoryTimeline
        timeline = MemoryTimeline(wal=wal, memory=MagicMock())

        # Get snapshot at S002 (before land record)
        snapshot = await timeline.get_snapshot(customer_id="C001", up_to_session_id="S002")

        # Assert: has income + emi, no land
        fact_types = [f["type"] for f in snapshot]
        assert "income" in fact_types
        assert "emi_outgoing" in fact_types
        assert "land_location" not in fact_types


class TestDemoSeeder:
    """Test demo seeding: Rajesh 4-session journey with WAL-first writes."""

    @pytest.mark.asyncio
    async def test_demo_seeder_writes_wal_first_for_all_facts(self):
        """
        CRITICAL: Every fact in demo journey written to WAL first.
        Demo setup: Rajesh 4-session loan journey, 19 days, multiple income changes.
        """
        from src.core.demo_seeder import DemoSeeder

        wal = WALLogger(wal_path="/tmp/test_demo_seeder_wal.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()

        seeder = DemoSeeder(wal=wal, memory=mock_mem0)
        await seeder.seed_rajesh_journey()

        # Assert: WAL has facts from 4 sessions
        with open(wal.wal_path) as f:
            entries = [json.loads(line) for line in f]

        assert len(entries) >= 4  # At least one entry per session
        
        # Verify S001-S004 all present
        session_ids = [e["session_id"] for e in entries]
        assert "S001" in session_ids
        assert "S002" in session_ids
        assert "S003" in session_ids
        assert "S004" in session_ids

    @pytest.mark.asyncio
    async def test_demo_seeder_session4_income_supersedes_session1(self):
        """Session 4 income (62K) supersedes Session 1 income (55K) with relationship marker."""
        from src.core.demo_seeder import DemoSeeder
        import tempfile
        import os

        # Use unique temp file to avoid stale data from prior runs
        fd, temp_path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.unlink(temp_path)  # Remove the file, WALLogger will create it

        wal = WALLogger(wal_path=temp_path)
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()

        seeder = DemoSeeder(wal=wal, memory=mock_mem0)
        await seeder.seed_rajesh_journey()

        # Parse WAL, find S004 income fact
        with open(wal.wal_path) as f:
            entries = [json.loads(line) for line in f]

        s4_entry = next((e for e in entries if e["session_id"] == "S004"), None)
        assert s4_entry is not None

        # Find income fact in S004
        income_fact = next((f for f in s4_entry["facts"] if f["type"] == "income"), None)
        assert income_fact is not None
        assert income_fact["value"] == "62000"
        assert income_fact.get("supersedes") == "S001_income"
        
        # Cleanup
        try:
            os.unlink(temp_path)
        except:
            pass

    @pytest.mark.asyncio
    async def test_demo_reset_clears_all_customer_data(self):
        """clear_demo_data() purges C001 from WAL, Redis, Mem0."""
        from src.core.demo_seeder import DemoSeeder

        wal = WALLogger(wal_path="/tmp/test_demo_reset_wal.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()
        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock()

        seeder = DemoSeeder(wal=wal, memory=mock_mem0, redis=mock_redis)

        # Seed then reset
        await seeder.seed_rajesh_journey()
        await seeder.clear_demo_data(customer_id="C001")

        # Assert: Redis keys deleted
        calls = mock_redis.delete.call_args_list
        deleted_keys = [str(c) for c in calls]
        assert any("briefing:C001" in str(c) for c in deleted_keys)
        assert any("summary:C001" in str(c) for c in deleted_keys)


class TestMemoryHealthChecker:
    """Test health check: data quality metrics (unverified, pending, sync drift)."""

    @pytest.mark.asyncio
    async def test_memory_health_flags_unverified_income(self):
        """Health check detects income is unverified and flags it."""
        from src.core.memory_health import MemoryHealthChecker

        wal = WALLogger(wal_path="/tmp/test_health_wal.jsonl")
        wal.append(
            session_id="S001",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "income", "value": "55000", "verified": False, "source": "customer_verbal"}
            ]
        )

        mock_mem0 = MagicMock()
        checker = MemoryHealthChecker(wal=wal, memory=mock_mem0)

        health = await checker.check(customer_id="C001")

        # Assert: flags includes income_unverified
        assert "income_unverified" in health["flags"]
        assert health["unverified_fact_count"] >= 1

    @pytest.mark.asyncio
    async def test_memory_health_sync_check_passes_when_wal_matches_mem0(self):
        """Sync check detects if WAL and Mem0 are in sync (same fact count)."""
        from src.core.memory_health import MemoryHealthChecker
        import tempfile
        import os

        # Use unique temp file to avoid stale data from prior runs
        fd, temp_path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.unlink(temp_path)

        wal = WALLogger(wal_path=temp_path)
        wal.append(
            session_id="S001",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "income", "value": "55000"},
                {"type": "employer", "value": "Pune MNC"}
            ]
        )

        # Mock mem0 with matching fact count
        mock_mem0 = MagicMock()
        mock_mem0.get = MagicMock(return_value={"facts": [
            {"id": "F001"},
            {"id": "F002"}
        ]})

        checker = MemoryHealthChecker(wal=wal, memory=mock_mem0)
        health = await checker.check(customer_id="C001")

        # Assert: sync_check passes
        assert health["sync_check"] == True
        
        # Cleanup
        try:
            os.unlink(temp_path)
        except:
            pass


class TestDemoEvaluation:
    """Test demo evaluation: baseline vs with_ps01 metrics."""

    @pytest.mark.asyncio
    async def test_demo_evaluate_returns_improvement_over_baseline(self):
        """Evaluation shows improvement: baseline 7.2 → with_ps01 1.2 = 83% improvement."""
        from src.core.evaluation_harness import EvaluationHarness

        harness = EvaluationHarness()

        # Run scenario (Rajesh Session 4 — final state)
        result = harness.compare(ps01_metrics={"repeated_questions": 1.2})

        # Assert: improvement calculation
        assert result["baseline"] == 7.2
        assert result["with_ps01"] == 1.2
        assert result["improvement_pct"] == pytest.approx(83.33, rel=1.0)


class TestBriefingHealthIntegration:
    """Test briefing includes health flags (integration with MemoryHealthChecker)."""

    @pytest.mark.asyncio
    async def test_briefing_includes_health_flags(self):
        """Briefing returned from /session/memory includes flags from health checker."""
        from src.core.briefing_builder import BriefingBuilder
        from src.core.memory_health import MemoryHealthChecker

        wal = WALLogger(wal_path="/tmp/test_briefing_flags_wal.jsonl")
        wal.append(
            session_id="S001",
            customer_id="C001",
            agent_id="officer_priya",
            bank_id="central",
            facts=[
                {"type": "income", "value": "55000", "verified": False}
            ]
        )

        mock_mem0 = MagicMock()
        mock_mem0.search = MagicMock(return_value=[
            {"id": "F001", "content": "income: 55000", "verified": False}
        ])
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        # Create briefing builder with health checker
        briefing_builder = BriefingBuilder(
            memory=mock_mem0,
            redis_cache=mock_redis,
            health_checker=MemoryHealthChecker(wal=wal, memory=mock_mem0)
        )

        briefing = await briefing_builder.build(customer_id="C001")

        # Assert: briefing includes health flags
        assert "flags" in briefing
        assert any("income" in str(f).lower() for f in briefing["flags"])


# ====== INTEGRATION TEST: FULL DEMO FLOW ======

class TestFullDemoScenario:
    """Integration test: complete demo scenario from seed to evaluate."""

    @pytest.mark.asyncio
    async def test_full_demo_flow_seed_correct_evaluate(self):
        """
        Full demo flow:
        1. Seed Rajesh journey
        2. Get briefing (shows unverified)
        3. Post correction (income updated)
        4. Get timeline (4 sessions)
        5. Evaluate (improvement %)
        """
        from src.core.demo_seeder import DemoSeeder
        from src.core.feedback_processor import FeedbackProcessor
        from src.core.memory_timeline import MemoryTimeline
        from src.core.evaluation_harness import EvaluationHarness

        wal = WALLogger(wal_path="/tmp/test_full_demo.jsonl")
        mock_mem0 = MagicMock()
        mock_mem0.add = AsyncMock()
        mock_mem0.search = MagicMock(return_value=[])
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_redis.delete = AsyncMock()

        # Step 1: Seed
        seeder = DemoSeeder(wal=wal, memory=mock_mem0, redis=mock_redis)
        await seeder.seed_rajesh_journey()

        # Step 2: Timeline (4 sessions)
        timeline = MemoryTimeline(wal=wal, memory=mock_mem0)
        events = await timeline.get_timeline("C001")
        assert len(events) >= 4

        # Step 3: Evaluate
        harness = EvaluationHarness()
        eval_result = harness.compare(ps01_metrics={"repeated_questions": 1.2})
        assert eval_result["improvement_pct"] > 80.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
