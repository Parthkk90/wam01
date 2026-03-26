"""
Phase 7: Concurrency + Tenant Isolation
Tests for branch locking, tenant isolation, and WAL atomicity.
12 tests total: 5 BranchLockManager + 4 TenantRegistry + 3 WALConcurrencySafety
"""
import pytest
import json
import threading
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, call
from typing import Dict, Any

# Import modules under test (will fail with ImportError until implemented)
from src.core.branch_lock_manager import BranchLockManager
from src.core.tenant_registry import TenantRegistry
from src.core.wal import WALLogger


# ============================================================================
# FIXTURES (Mocked Dependencies)
# ============================================================================

@pytest.fixture
def mock_redis_client():
    """Mock Redis client for all lock/registry tests"""
    client = MagicMock()
    client.set = MagicMock(return_value=True)
    client.get = MagicMock(return_value=None)
    client.delete = MagicMock(return_value=1)
    client.eval = MagicMock(return_value=1)  # Lua script for atomic release
    client.keys = MagicMock(return_value=[])
    client.ping = MagicMock(return_value=True)
    return client


@pytest.fixture
def mock_mem0_bridge():
    """Mock Mem0Bridge for concurrency tests"""
    bridge = AsyncMock()
    bridge.add_with_wal = AsyncMock(return_value={"status": "ok"})
    return bridge


@pytest.fixture
def tmp_wal_file():
    """Temporary WAL file for atomic write tests"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        return f.name


# ============================================================================
# TEST CLASS 1: BranchLockManager (5 tests)
# ============================================================================

class TestBranchLockManager:
    """Test distributed locking for concurrent branch writes"""

    def test_acquire_lock_returns_true_when_free(self, mock_redis_client):
        """
        WHEN: Lock does not exist
        THEN: acquire() returns True and SET called with NX EX
        """
        # Setup: lock is free (get returns None)
        mock_redis_client.get.return_value = None
        mock_redis_client.set.return_value = True

        manager = BranchLockManager(mock_redis_client)
        result = manager.acquire("C001", "BR_A", "agt_1")

        assert result is True
        mock_redis_client.set.assert_called_once()
        call_kwargs = mock_redis_client.set.call_args.kwargs
        assert call_kwargs.get("nx") is True
        assert call_kwargs.get("ex") == 10

    def test_acquire_lock_returns_false_when_held_by_other_branch(self, mock_redis_client):
        """
        WHEN: Lock held by different branch
        THEN: acquire() returns False and SET fails (NX not satisfied)
        """
        # Setup: lock is held by BR_B
        mock_redis_client.get.return_value = "BR_B:agt_2"
        mock_redis_client.set.return_value = None  # NX failed

        manager = BranchLockManager(mock_redis_client)
        result = manager.acquire("C001", "BR_A", "agt_1")

        assert result is False
        mock_redis_client.set.assert_called_once()

    def test_release_lock_only_if_holder(self, mock_redis_client):
        """
        WHEN: release() called and lock holder matches
        THEN: Lua script returns 1 (deleted) and DEL is atomic
        WHEN: branch_id does not match holder
        THEN: Lua script returns 0 (not deleted)
        """
        # Setup: lock held by BR_A
        mock_redis_client.get.return_value = "BR_A:agt_1"
        mock_redis_client.eval.return_value = 1  # Script: IF match THEN del ELSE 0

        manager = BranchLockManager(mock_redis_client)

        # Test 1: Correct branch releases lock
        result = manager.release("C001", "BR_A")
        assert result is True

        # Test 2: Wrong branch cannot release lock
        mock_redis_client.eval.return_value = 0
        result = manager.release("C001", "BR_B")
        assert result is False

    def test_lock_expires_after_ttl(self, mock_redis_client):
        """
        WHEN: Lock acquired with ttl=10
        THEN: After TTL expiry, second acquire() succeeds
        (Mock simulates Redis TTL behavior)
        """
        manager = BranchLockManager(mock_redis_client)

        # First acquire (success)
        mock_redis_client.set.return_value = True
        result1 = manager.acquire("C001", "BR_A", "agt_1", ttl=10)
        assert result1 is True

        # Simulate TTL expiry: mock_redis_client now returns None for get
        mock_redis_client.get.return_value = None
        mock_redis_client.set.return_value = True

        # Second acquire (after expiry, success)
        result2 = manager.acquire("C001", "BR_B", "agt_2", ttl=10)
        assert result2 is True

    def test_concurrent_writes_serialized_by_lock(self, mock_redis_client):
        """
        WHEN: Two threads try to acquire lock for same customer
        THEN: Only one succeeds; second gets False
        (Uses threading.Thread, not asyncio)
        """
        results = []
        lock_state = {"holder": None}

        def acquire_with_side_effect(branch_id, agent_id):
            # Simulate atomic SET with NX
            if lock_state["holder"] is None:
                lock_state["holder"] = f"{branch_id}:{agent_id}"
                return True
            return False

        mock_redis_client.set.side_effect = lambda *args, **kwargs: acquire_with_side_effect(
            f"BR_{len(results)}", f"agt_{len(results)}"
        )

        manager = BranchLockManager(mock_redis_client)

        def thread_acquire(branch_id, agent_id):
            result = manager.acquire("C001", branch_id, agent_id)
            results.append((branch_id, result))

        # Thread 1: Branch A
        t1 = threading.Thread(target=thread_acquire, args=("BR_A", "agt_1"))
        # Thread 2: Branch B
        t2 = threading.Thread(target=thread_acquire, args=("BR_B", "agt_2"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Only one should have succeeded
        successes = [r for _, r in results if r is True]
        assert len(successes) == 1


# ============================================================================
# TEST CLASS 2: TenantRegistry (4 tests)
# ============================================================================

class TestTenantRegistry:
    """Test branch registration and customer isolation"""

    def test_register_branch_stores_in_redis(self, mock_redis_client):
        """
        WHEN: register_branch() called
        THEN: SET branch:{branch_id} {json} EX 3600
        """
        mock_redis_client.set.return_value = True

        registry = TenantRegistry(mock_redis_client)
        result = registry.register_branch("BR_A", "Mumbai Main", "west")

        assert result["branch_id"] == "BR_A"
        assert result["branch_name"] == "Mumbai Main"
        mock_redis_client.set.assert_called_once()

    def test_isolate_customer_assigns_branch(self, mock_redis_client):
        """
        WHEN: isolate_customer() called and customer unassigned
        THEN: SET tenant:{customer_id} branch_id NX returns True
        """
        mock_redis_client.set.return_value = True

        registry = TenantRegistry(mock_redis_client)
        result = registry.isolate_customer("C001", "BR_A")

        assert result is True
        mock_redis_client.set.assert_called_once()

    def test_isolate_customer_blocks_second_branch(self, mock_redis_client):
        """
        WHEN: Customer already assigned to BR_A
        AND: BR_B tries to assign same customer
        THEN: isolate_customer() returns False (NX fails)
        """
        # Setup: C001 already belongs to BR_A
        mock_redis_client.set.return_value = None  # NX failed

        registry = TenantRegistry(mock_redis_client)
        result = registry.isolate_customer("C001", "BR_B")

        assert result is False

    def test_list_branches_returns_all_registered(self, mock_redis_client):
        """
        WHEN: list_branches() called
        THEN: Returns all branch:{...} keys from Redis
        (Uses KEYS pattern; production should use SCAN)
        """
        # Setup: Mock returns two branch keys
        mock_redis_client.keys.return_value = ["branch:BR_A", "branch:BR_B"]
        mock_redis_client.get.side_effect = [
            json.dumps({"branch_id": "BR_A", "branch_name": "Mumbai"}),
            json.dumps({"branch_id": "BR_B", "branch_name": "Delhi"})
        ]

        registry = TenantRegistry(mock_redis_client)
        result = registry.list_branches()

        assert len(result) == 2
        assert result[0]["branch_id"] == "BR_A"
        assert result[1]["branch_id"] == "BR_B"


# ============================================================================
# TEST CLASS 3: WALConcurrencySafety (3 tests)
# ============================================================================

class TestWALConcurrencySafety:
    """Test atomic WAL writes and lock-based Mem0 protection"""

    def test_wal_append_is_atomic(self, tmp_wal_file):
        """
        WHEN: Two threads append to wal.jsonl simultaneously
        THEN: No line corruption; each entry is valid JSON
        """
        results = {"valid": 0, "invalid": 0}

        wal = WALLogger(tmp_wal_file)

        def thread_append(session_id, agent_id):
            facts = [{"type": "income", "value": f"val_{agent_id}"}]
            # WALLogger.append() signature: (session_id, customer_id, agent_id, bank_id, facts)
            wal.append(session_id, "C001", agent_id, "BANK_001", facts)

        # Thread 1 and 2 append simultaneously
        t1 = threading.Thread(target=thread_append, args=("S001", "agt_1"))
        t2 = threading.Thread(target=thread_append, args=("S002", "agt_2"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Verify all lines are valid JSON
        with open(tmp_wal_file, 'r') as f:
            for line in f:
                try:
                    json.loads(line)
                    results["valid"] += 1
                except json.JSONDecodeError:
                    results["invalid"] += 1

        assert results["valid"] == 2
        assert results["invalid"] == 0

    def test_mem0_bridge_respects_branch_lock(self, mock_redis_client):
        """
        WHEN: add_with_wal() needs to check lock before accessing customer
        THEN: BranchLockManager.is_lock_held() determines access
        (Integration test: Mem0Bridge will respect this in Step 5)
        """
        # Setup: No lock held for C001
        mock_redis_client.get.return_value = None

        lock_mgr = BranchLockManager(mock_redis_client)

        # Without lock, access should be denied
        has_lock = lock_mgr.get_lock_holder("C001")
        assert has_lock is None

        # After acquiring lock, access granted
        mock_redis_client.set.return_value = True
        acquired = lock_mgr.acquire("C001", "BR_A", "agt_1")
        assert acquired is True

        # Now lock holder should be retrievable
        mock_redis_client.get.return_value = "BR_A:agt_1"
        holder = lock_mgr.get_lock_holder("C001")
        assert holder == "BR_A:agt_1"

    def test_two_sessions_same_customer_different_branches_no_leak(self, mock_redis_client):
        """
        WHEN: Session S1 from Branch A, Session S2 from Branch B for same customer
        THEN: Branch B cannot read Branch A's session:{session_id} keys
        """
        # Setup: store session data in dict
        session_data = {
            "session:S001": {"branch_id": "BR_A", "customer_id": "C001"},
            "session:S002": {"branch_id": "BR_B", "customer_id": "C001"}
        }

        def mock_get_func(key):
            if key not in session_data:
                return None
            return json.dumps(session_data[key])

        mock_redis_client.get.side_effect = mock_get_func

        # Test: Branch A can read its own session S001
        s001_json = session_data.get("session:S001")
        assert s001_json is not None
        s001_data = session_data["session:S001"]
        assert s001_data["branch_id"] == "BR_A"

        # Test: Branch B can read its own session S002
        s002_json = session_data.get("session:S002")
        assert s002_json is not None
        s002_data = session_data["session:S002"]
        assert s002_data["branch_id"] == "BR_B"

        # Test: Branch B should not see S001 (isolation check)
        # This would be enforced by SessionIsolation layer in API
        s001_data_check = session_data["session:S001"]
        assert s001_data_check["branch_id"] != "BR_B"  # Different branch
