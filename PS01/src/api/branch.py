"""
Phase 7: Branch Management API Router
Endpoints for branch registration and customer-to-branch isolation.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Annotated
import logging

from src.core.branch_lock_manager import BranchLockManager
from src.core.tenant_registry import TenantRegistry
from src.api.models import (
    BranchRegisterRequest,
    BranchInfo,
    CustomerAssignRequest,
    CustomerAssignResponse,
    BranchListResponse,
)
from src.api.dependencies import get_branch_lock_manager, get_tenant_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/branch", tags=["branch"])


@router.post("/register")
async def register_branch(
    req: BranchRegisterRequest,
    registry: Annotated[TenantRegistry, Depends(get_tenant_registry)],
) -> BranchInfo:
    """
    Register a new branch in the system.

    Args:
        req: Branch registration details (branch_id, branch_name, region)
        registry: TenantRegistry dependency

    Returns:
        Branch registration record with timestamp
    """
    try:
        result = registry.register_branch(req.branch_id, req.branch_name, req.region)
        logger.info(f"Branch registered: {req.branch_id}")
        return BranchInfo(**result)
    except Exception as e:
        logger.error(f"Failed to register branch {req.branch_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{branch_id}")
async def get_branch(
    branch_id: str,
    registry: Annotated[TenantRegistry, Depends(get_tenant_registry)],
) -> BranchInfo:
    """
    Retrieve branch metadata by ID.

    Args:
        branch_id: Branch ID to look up
        registry: TenantRegistry dependency

    Returns:
        Branch information or 404 if not found
    """
    result = registry.get_branch(branch_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Branch {branch_id} not found")
    return BranchInfo(**result)


@router.post("/assign-customer")
async def assign_customer(
    req: CustomerAssignRequest,
    registry: Annotated[TenantRegistry, Depends(get_tenant_registry)],
) -> CustomerAssignResponse:
    """
    Assign customer to a branch (one-time, immutable).

    Once assigned, customer is locked to that branch permanently.
    Prevents cross-branch access.

    Args:
        req: Customer-to-branch assignment (customer_id, branch_id)
        registry: TenantRegistry dependency

    Returns:
        Assignment status (newly assigned or already assigned)
    """
    assigned = registry.isolate_customer(req.customer_id, req.branch_id)

    status = "assigned" if assigned else "already_assigned"
    result_branch_id = (
        req.branch_id
        if assigned
        else registry.get_customer_branch(req.customer_id)
    )

    return CustomerAssignResponse(
        status=status, customer_id=req.customer_id, branch_id=result_branch_id
    )


@router.get("/list")
async def list_branches(
    registry: Annotated[TenantRegistry, Depends(get_tenant_registry)],
) -> BranchListResponse:
    """
    List all registered branches.

    Returns:
        All branch records currently registered
    """
    try:
        branches_data = registry.list_branches()
        branches = [BranchInfo(**b) for b in branches_data]
        return BranchListResponse(branches=branches, count=len(branches))
    except Exception as e:
        logger.error(f"Failed to list branches: {e}")
        raise HTTPException(status_code=500, detail=str(e))
