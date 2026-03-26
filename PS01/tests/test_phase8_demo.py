"""
Phase 8: Demo Hardening + Deployment
Tests for deployment validation, full demo runner, and document generation.
10 tests total: 4 DeploymentValidator + 4 DemoRunner + 2 DocumentGeneration
"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, call
from typing import Dict, Any

# Imports for existing modules
from src.core.wal import WALLogger
from src.core.demo_seeder import DemoSeeder
from src.core.evaluation_harness import EvaluationHarness
from src.core.briefing_builder import BriefingBuilder
from src.core.memory_health import MemoryHealthChecker

# Flag to determine if Phase 8 modules are ready
PHASE8_READY = True
try:
    from src.core.deployment_validator import DeploymentValidator
    from src.core.demo_runner import DemoRunner
except ImportError:
    PHASE8_READY = False
    # Create dummy classes so tests can reference them
    DeploymentValidator = MagicMock
    DemoRunner = MagicMock


# ============================================================================
# FIXTURES (Mocked Dependencies)
# ============================================================================

@pytest.fixture
def mock_redis_client():
    """Mock Redis client for deployment validator."""
    client = MagicMock()
    client.ping = MagicMock(return_value=True)
    return client


@pytest.fixture
def mock_memory():
    """Mock Mem0 memory object."""
    memory = MagicMock()
    memory.search = MagicMock(return_value={"probe": "ok"})
    return memory


@pytest.fixture
def tmp_wal_path(tmp_path):
    """Temporary WAL file path for testing."""
    return str(tmp_path / "test_wal.jsonl")


@pytest.fixture
def tmp_docs_path(tmp_path):
    """Temporary docs directory for file output testing."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    return str(docs_dir)


@pytest.fixture
def mock_seeder():
    """Mock DemoSeeder."""
    seeder = MagicMock(spec=DemoSeeder)
    seeder.clear_demo_data = MagicMock(return_value={"status": "cleared"})
    seeder.seed_rajesh_journey = MagicMock(return_value={
        "sessions": 4,
        "facts": 8,
        "customer_id": "C001"
    })
    return seeder


@pytest.fixture
def mock_briefing_builder():
    """Mock BriefingBuilder."""
    builder = MagicMock(spec=BriefingBuilder)
    builder.build = MagicMock(return_value={
        "customer_id": "C001",
        "verified_facts": [],
        "unverified_facts": [],
        "flags": []
    })
    return builder


@pytest.fixture
def mock_health_checker():
    """Mock MemoryHealthChecker."""
    checker = MagicMock(spec=MemoryHealthChecker)
    checker.check = MagicMock(return_value={
        "fact_count": 3,
        "is_healthy": True,
        "flags": []
    })
    return checker


@pytest.fixture
def mock_evaluation():
    """Mock EvaluationHarness."""
    harness = MagicMock(spec=EvaluationHarness)
    harness.compare = MagicMock(return_value={
        "baseline": 7.2,
        "with_ps01": 3.1,
        "improvement_pct": 56.9
    })
    return harness


@pytest.fixture
def mock_validator(tmp_docs_path):
    """Mock DeploymentValidator with configurable health checks."""
    validator = MagicMock(spec=DeploymentValidator)
    validator.run_all = MagicMock(return_value={
        "ollama": True,
        "redis": True,
        "redpanda": True,
        "wal_integrity": True,
        "mem0": True,
        "all_healthy": True,
        "checked_at": "2026-03-26T10:00:00Z"
    })
    return validator


# ============================================================================
# TEST CLASS 1: DeploymentValidator (4 tests)
# ============================================================================

@pytest.mark.skipif(not PHASE8_READY, reason="Phase 8 modules not yet implemented")
class TestDeploymentValidator:
    """Test deployment health checks."""

    def test_check_ollama_true_when_phi4_in_models(
        self, mock_redis_client, mock_memory
    ):
        """
        WHEN: Ollama /api/tags returns phi4-mini in model list
        THEN: check_ollama() returns True
        """
        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "models": [
                    {"name": "phi4-mini"},
                    {"name": "nomic-embed-text"}
                ]
            }
            mock_get.return_value.status_code = 200

            validator = DeploymentValidator(
                memory=mock_memory,
                redis_client=mock_redis_client,
                wal_logger=None,
                ollama_base_url="http://localhost:11434"
            )
            result = validator.check_ollama()

            assert result is True
            mock_get.assert_called_once()

    def test_check_ollama_false_when_connection_error(
        self, mock_redis_client, mock_memory
    ):
        """
        WHEN: Ollama /api/tags raises ConnectionError
        THEN: check_ollama() returns False, no exception propagates
        """
        with patch("requests.get") as mock_get:
            import requests
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

            validator = DeploymentValidator(
                memory=mock_memory,
                redis_client=mock_redis_client,
                wal_logger=None,
                ollama_base_url="http://localhost:11434"
            )
            result = validator.check_ollama()

            assert result is False
            # No exception should propagate
            assert isinstance(result, bool)

    def test_check_wal_integrity_false_on_corrupt_line(self, mock_redis_client, mock_memory):
        """
        WHEN: wal.jsonl contains one valid + one invalid JSON line
        THEN: check_wal_integrity() returns False
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            wal_path = f.name
            # Valid line
            f.write(json.dumps({"session_id": "S001", "facts": []}) + "\n")
            # Invalid line
            f.write("THIS IS NOT JSON {{{\n")

        try:
            wal_logger = WALLogger(wal_path)
            validator = DeploymentValidator(
                memory=mock_memory,
                redis_client=mock_redis_client,
                wal_logger=wal_logger,
                ollama_base_url="http://localhost:11434"
            )
            result = validator.check_wal_integrity()

            assert result is False
        finally:
            Path(wal_path).unlink()

    def test_run_all_sets_all_healthy_false_if_one_fails(
        self, mock_redis_client, mock_memory
    ):
        """
        WHEN: Four checks pass but redpanda fails
        THEN: run_all() returns all_healthy=False
        """
        with patch("requests.get") as mock_get, \
             patch("confluent_kafka.Producer") as mock_producer:

            # Ollama OK
            mock_get.return_value.json.return_value = {"models": [{"name": "phi4-mini"}]}

            # Redpanda fails
            mock_producer.return_value.list_topics.side_effect = Exception("Broker unavailable")

            # Redis OK
            mock_redis_client.ping.return_value = True

            # Mem0 OK
            mock_memory.search.return_value = {"result": "ok"}

            validator = DeploymentValidator(
                memory=mock_memory,
                redis_client=mock_redis_client,
                wal_logger=None,
                ollama_base_url="http://localhost:11434"
            )

            result = validator.run_all()

            assert result["all_healthy"] is False
            assert result["redpanda"] is False
            # Other checks should still be True
            assert result["ollama"] is True
            assert result["redis"] is True


# ============================================================================
# TEST CLASS 2: DemoRunner (4 tests)
# ============================================================================

@pytest.mark.skipif(not PHASE8_READY, reason="Phase 8 modules not yet implemented")
class TestDemoRunner:
    """Test full demo runner."""

    def test_full_demo_aborts_if_validator_not_healthy(
        self,
        mock_seeder,
        mock_briefing_builder,
        mock_health_checker,
        mock_evaluation,
    ):
        """
        WHEN: DeploymentValidator.run_all() returns all_healthy=False
        THEN: run_full_demo() aborts without seeding
        """
        validator = MagicMock(spec=DeploymentValidator)
        validator.run_all.return_value = {"all_healthy": False}

        runner = DemoRunner(
            seeder=mock_seeder,
            briefing_builder=mock_briefing_builder,
            health_checker=mock_health_checker,
            evaluation=mock_evaluation,
            validator=validator
        )

        result = runner.run_full_demo()

        assert result["status"] == "aborted"
        # Seeder should NOT be called
        mock_seeder.clear_demo_data.assert_not_called()
        mock_seeder.seed_rajesh_journey.assert_not_called()

    def test_full_demo_clears_before_seeding(
        self,
        mock_seeder,
        mock_briefing_builder,
        mock_health_checker,
        mock_evaluation,
    ):
        """
        WHEN: run_full_demo() executes
        THEN: clear_demo_data() called before seed_rajesh_journey()
        """
        validator = MagicMock(spec=DeploymentValidator)
        validator.run_all.return_value = {"all_healthy": True}

        runner = DemoRunner(
            seeder=mock_seeder,
            briefing_builder=mock_briefing_builder,
            health_checker=mock_health_checker,
            evaluation=mock_evaluation,
            validator=validator
        )

        result = runner.run_full_demo()

        # Verify call order: clear then seed
        assert mock_seeder.clear_demo_data.call_count == 1
        assert mock_seeder.seed_rajesh_journey.call_count == 1

        # Check that clear was called before seed
        calls = mock_seeder.method_calls
        clear_idx = None
        seed_idx = None
        for i, method_call in enumerate(calls):
            if method_call[0] == 'clear_demo_data':
                clear_idx = i
            elif method_call[0] == 'seed_rajesh_journey':
                seed_idx = i

        assert clear_idx is not None and seed_idx is not None
        assert clear_idx < seed_idx  # clear before seed

    def test_full_demo_returns_4_sessions_replayed(
        self,
        mock_seeder,
        mock_briefing_builder,
        mock_health_checker,
        mock_evaluation,
    ):
        """
        WHEN: run_full_demo() completes successfully
        THEN: Returns sessions_replayed=4, facts_total=8
        """
        validator = MagicMock(spec=DeploymentValidator)
        validator.run_all.return_value = {"all_healthy": True}

        runner = DemoRunner(
            seeder=mock_seeder,
            briefing_builder=mock_briefing_builder,
            health_checker=mock_health_checker,
            evaluation=mock_evaluation,
            validator=validator
        )

        result = runner.run_full_demo()

        assert result["status"] == "completed"
        assert result["sessions_replayed"] == 4
        assert result["facts_total"] == 8

    def test_judge_summary_mentions_improvement_and_wal(
        self, mock_seeder, mock_briefing_builder, mock_health_checker, mock_evaluation
    ):
        """
        WHEN: _build_judge_summary() called with metrics
        THEN: Returns plain English text mentioning improvement%, WAL, PAN
        """
        validator = MagicMock(spec=DeploymentValidator)
        validator.run_all.return_value = {"all_healthy": True}

        runner = DemoRunner(
            seeder=mock_seeder,
            briefing_builder=mock_briefing_builder,
            health_checker=mock_health_checker,
            evaluation=mock_evaluation,
            validator=validator
        )

        metrics = {"improvement_pct": 56.9, "baseline": 7.2, "with_ps01": 3.1}
        summary = runner._build_judge_summary(metrics)

        # Verify content
        assert isinstance(summary, str)
        assert len(summary) > 80  # Substantial paragraph
        assert "56" in summary or "57" in summary  # improvement pct
        assert "WAL" in summary or "write" in summary.lower()  # WAL durability
        assert "PAN" in summary or "Aadhaar" in summary  # PII protection


# ============================================================================
# TEST CLASS 3: DocumentGeneration (2 tests)
# ============================================================================

@pytest.mark.skipif(not PHASE8_READY, reason="Phase 8 modules not yet implemented")
class TestDocumentGeneration:
    """Test document generation side effects."""

    def test_demo_script_written_to_docs_folder(
        self,
        tmp_path,
        mock_seeder,
        mock_briefing_builder,
        mock_health_checker,
        mock_evaluation,
    ):
        """
        WHEN: run_full_demo() completes
        THEN: docs/DEMO_SCRIPT.md is created with Session 4 and Q&A sections
        """
        # Setup docs directory in tmp_path
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        validator = MagicMock(spec=DeploymentValidator)
        validator.run_all.return_value = {"all_healthy": True}

        runner = DemoRunner(
            seeder=mock_seeder,
            briefing_builder=mock_briefing_builder,
            health_checker=mock_health_checker,
            evaluation=mock_evaluation,
            validator=validator,
            docs_path=str(docs_dir)  # Override docs path for testing
        )

        result = runner.run_full_demo()

        # Verify DEMO_SCRIPT.md was created
        demo_script_path = docs_dir / "DEMO_SCRIPT.md"
        assert demo_script_path.exists(), f"DEMO_SCRIPT.md not found at {demo_script_path}"

        content = demo_script_path.read_text()
        assert "Session 4" in content, "Session 4 section missing"
        assert "THE DEMO MOMENT" in content, "Demo moment highlight missing"
        assert "Judge Q&A" in content, "Q&A section missing"

    def test_deployment_status_written_on_run_all(
        self, tmp_path, mock_redis_client, mock_memory
    ):
        """
        WHEN: DeploymentValidator.run_all() completes with all healthy
        THEN: docs/DEPLOYMENT_STATUS.md is created with status table
        """
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = {
                "models": [{"name": "phi4-mini"}]
            }
            mock_redis_client.ping.return_value = True
            mock_memory.search.return_value = {"ok": True}

            validator = DeploymentValidator(
                memory=mock_memory,
                redis_client=mock_redis_client,
                wal_logger=None,
                ollama_base_url="http://localhost:11434",
                docs_path=str(docs_dir)
            )

            result = validator.run_all()

            # Verify DEPLOYMENT_STATUS.md was created
            status_path = docs_dir / "DEPLOYMENT_STATUS.md"
            assert status_path.exists(), f"DEPLOYMENT_STATUS.md not found at {status_path}"

            content = status_path.read_text()
            assert "READY" in content or "Ollama" in content, "Status content missing"
            assert "Ollama" in content, "Ollama service not mentioned"
            assert "Redis" in content, "Redis service not mentioned"
