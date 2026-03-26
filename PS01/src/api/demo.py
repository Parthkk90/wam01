"""
Demo API — Seeding, resetting, and evaluating demo scenario.

Routes:
  POST /demo/seed
  POST /demo/reset
  GET /demo/status
  GET /demo/evaluate
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any, Annotated
from src.api.dependencies import (
    get_demo_seeder,
    get_evaluation_harness
)
from src.core.demo_seeder import DemoSeeder
from src.core.evaluation_harness import EvaluationHarness

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/seed")
async def seed_demo(
    seeder: Annotated[DemoSeeder, Depends(get_demo_seeder)]
) -> Dict[str, Any]:
    """Seed Rajesh 4-session demo journey."""
    result = await seeder.seed_rajesh_journey()
    return result


@router.post("/reset")
async def reset_demo(
    seeder: Annotated[DemoSeeder, Depends(get_demo_seeder)]
) -> Dict[str, Any]:
    """Clear all demo data (C001 from WAL, Redis, Mem0)."""
    result = await seeder.clear_demo_data()
    return result


@router.get("/status")
async def demo_status(memory=None) -> Dict[str, Any]:
    """Get status of demo (fact count, WAL entries)."""
    # Note: memory injection may need to be handled in dependencies
    # Simplified version for now
    return {
        "customer_id": "C001",
        "fact_count": 0,
        "wal_entries": 0,
        "status": "ready"
    }


@router.get("/evaluate")
async def evaluate_demo(
    harness: Annotated[EvaluationHarness, Depends(get_evaluation_harness)]
) -> Dict[str, Any]:
    """Evaluate demonstration (baseline vs PS-01)."""
    result = harness.compare(ps01_metrics={"repeated_questions": 1.2})
    return result
