"""
TenantRegistry: Multi-tenant branch registry and customer isolation.

Manages branch registration and ensures customer-to-branch isolation via Redis.
Prevents double-assignment of customers to multiple branches using SET NX.

Key schemas:
  - branch:{branch_id} → {branch_name, region, registered_at}  (TTL: 3600)
  - tenant:{customer_id} → branch_id  (no TTL, persistent)
"""
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, UTC

logger = logging.getLogger(__name__)


class TenantRegistry:
    """
    Multi-tenant registry managing branch registrations and customer isolation.
    """

    def __init__(self, redis_client):
        """
        Initialize registry with Redis client.

        Args:
            redis_client: Redis client instance (or mock)
        """
        self.redis = redis_client

    def register_branch(
        self, branch_id: str, branch_name: str, region: str
    ) -> Dict[str, Any]:
        """
        Register a new branch in the system.

        Stores branch metadata with TTL=3600 (1 hour).
        Does not expire; branch info is cached but will refresh if needed.

        Args:
            branch_id: Unique branch ID (e.g., "BR_A")
            branch_name: Human-readable branch name (e.g., "Mumbai Main")
            region: Geographic region (e.g., "west", "east")

        Returns:
            dict: Branch registration record with registered_at timestamp
        """
        data = {
            "branch_id": branch_id,
            "branch_name": branch_name,
            "region": region,
            "registered_at": datetime.now(UTC).isoformat() + "Z"
        }

        branch_key = f"branch:{branch_id}"
        self.redis.set(
            branch_key,
            json.dumps(data),
            ex=3600  # TTL: 1 hour
        )

        logger.info(f"Branch registered: {branch_id} ({branch_name})")
        return data

    def get_branch(self, branch_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve branch metadata by ID.

        Args:
            branch_id: Branch ID to look up

        Returns:
            dict: Branch data or None if not registered
        """
        branch_key = f"branch:{branch_id}"
        data_json = self.redis.get(branch_key)

        if data_json is None:
            return None

        return json.loads(data_json)

    def list_branches(self) -> List[Dict[str, Any]]:
        """
        List all registered branches.

        Note: Uses KEYS pattern matching (not SCAN for simplicity in tests).
        Production should use SCAN to avoid blocking on large datasets.

        Returns:
            list: All branch records currently registered
        """
        # Pattern match all branch:{...} keys
        keys = self.redis.keys("branch:*")
        branches = []

        for key in keys:
            data_json = self.redis.get(key)
            if data_json:
                try:
                    branches.append(json.loads(data_json))
                except json.JSONDecodeError:
                    logger.warning(f"Corrupted branch record: {key}")

        return branches

    def isolate_customer(self, customer_id: str, branch_id: str) -> bool:
        """
        Assign customer to a branch (one-time, immutable).

        Uses Redis SET NX to ensure a customer can only be assigned once.
        Once assigned, customer is locked to that branch permanently.

        Args:
            customer_id: Customer ID to assign (e.g., "C001")
            branch_id: Branch ID to assign to (e.g., "BR_A")

        Returns:
            bool: True if customer newly assigned, False if already assigned
        """
        tenant_key = f"tenant:{customer_id}"

        result = self.redis.set(
            tenant_key,
            branch_id,
            nx=True  # Only set if key does not exist
        )

        success = result is not None and result is True

        if success:
            logger.info(f"Customer {customer_id} assigned to branch {branch_id}")
        else:
            existing_branch = self.redis.get(tenant_key)
            logger.debug(
                f"Customer {customer_id} already assigned to {existing_branch}"
            )

        return success

    def get_customer_branch(self, customer_id: str) -> Optional[str]:
        """
        Retrieve the branch assigned to a customer.

        Args:
            customer_id: Customer ID to look up

        Returns:
            str: Branch ID or None if not yet assigned
        """
        tenant_key = f"tenant:{customer_id}"
        return self.redis.get(tenant_key)

    def verify_customer_branch(self, customer_id: str, branch_id: str) -> bool:
        """
        Verify that a customer belongs to a specific branch.

        Used in read operations to enforce branch isolation.

        Args:
            customer_id: Customer ID
            branch_id: Branch ID to verify

        Returns:
            bool: True if customer belongs to branch, False otherwise
        """
        assigned_branch = self.get_customer_branch(customer_id)
        return assigned_branch == branch_id
