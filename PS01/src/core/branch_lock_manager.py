"""
BranchLockManager: Distributed locking for concurrent branch writes.

Ensures that simultaneous writes from different branches to the same customer
are serialized via Redis distributed locks. Uses atomic SET NX for acquire
and Lua script for atomic check-and-delete release.

Key schema: lock:{customer_id} → "{branch_id}:{agent_id}"
TTL: 10 seconds (configurable)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BranchLockManager:
    """
    Distributed lock manager using Redis SET NX for acquire,
    Lua script for atomic release.
    """

    # Lua script for atomic check-and-delete
    RELEASE_SCRIPT = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
      return redis.call('DEL', KEYS[1])
    else
      return 0
    end
    """

    def __init__(self, redis_client):
        """
        Initialize lock manager with Redis client.

        Args:
            redis_client: Redis client instance (or mock)
        """
        self.redis = redis_client

    def acquire(self, customer_id: str, branch_id: str, agent_id: str, ttl: int = 10) -> bool:
        """
        Acquire distributed lock for customer_id.

        Uses Redis SET with NX (only if not exists) and EX (TTL).
        Returns True if lock acquired, False if already held.

        Args:
            customer_id: Customer ID (e.g., "C001")
            branch_id: Branch ID (e.g., "BR_A")
            agent_id: Agent ID (e.g., "agt_1")
            ttl: Lock TTL in seconds (default: 10)

        Returns:
            bool: True if lock acquired, False if already held
        """
        lock_key = f"lock:{customer_id}"
        lock_value = f"{branch_id}:{agent_id}"

        result = self.redis.set(
            lock_key,
            lock_value,
            nx=True,  # Only set if key does not exist
            ex=ttl    # Expiration time in seconds
        )

        # redis.set() returns True if set, None if NX failed
        success = result is not None and result is True
        
        if success:
            logger.debug(f"Lock acquired: {lock_key} by {lock_value}")
        else:
            logger.debug(f"Lock already held for {lock_key}")

        return success

    def release(self, customer_id: str, branch_id: str) -> bool:
        """
        Release distributed lock if held by branch_id.

        Uses Lua script for atomic GET→compare→DELETE operation.
        Prevents one branch from releasing another branch's lock.

        Args:
            customer_id: Customer ID
            branch_id: Branch ID that must match lock holder

        Returns:
            bool: True if lock released, False if not held or holder mismatch
        """
        lock_key = f"lock:{customer_id}"

        result = self.redis.eval(
            self.RELEASE_SCRIPT,
            1,                # number of keys
            lock_key,         # KEYS[1]
            branch_id         # ARGV[1]
        )

        # Lua returns 1 if deleted, 0 if mismatch or not found
        success = result == 1

        if success:
            logger.debug(f"Lock released: {lock_key} by {branch_id}")
        else:
            logger.debug(f"Lock release failed for {lock_key} by {branch_id}")

        return success

    def get_lock_holder(self, customer_id: str) -> Optional[str]:
        """
        Get current lock holder for customer_id.

        Returns:
            str: Lock holder value "{branch_id}:{agent_id}" or None if not held
        """
        lock_key = f"lock:{customer_id}"
        holder = self.redis.get(lock_key)
        return holder
