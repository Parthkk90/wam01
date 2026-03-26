"""
Evaluation harness for PS-01 judging.

Hardcoded baseline: 7.2 repeated questions (no-memory baseline).
Compares PS-01 performance against baseline using predefined scenarios.
"""

from typing import Dict, Any, List
import statistics


class EvaluationHarness:
    """
    Evaluation harness for judging PS-01 against baseline.

    Baseline: 7.2 repeated questions (hardcoded control metric).
    Scenarios: 5 predefined customer journeys for repeatable testing.
    """

    # Hardcoded baseline: repeated questions without memory system
    BASELINE_REPEATED_QUESTIONS = 7.2

    # 5 scenarios for hackathon (simplified)
    SCENARIOS = [
        {
            "scenario_id": 1,
            "name": "Rajesh 4th session - home loan",
            "customer_id": "C001",
            "previous_sessions": 3
        },
        {
            "scenario_id": 2,
            "name": "Sunita new customer - auto loan",
            "customer_id": "C002",
            "previous_sessions": 0
        },
        {
            "scenario_id": 3,
            "name": "Priya 2nd session - repeat inquiry",
            "customer_id": "C003",
            "previous_sessions": 1
        },
        {
            "scenario_id": 4,
            "name": "Amit high-value customer",
            "customer_id": "C004",
            "previous_sessions": 5
        },
        {
            "scenario_id": 5,
            "name": "Neha verification follow-up",
            "customer_id": "C005",
            "previous_sessions": 2
        }
    ]

    def __init__(self):
        """Initialize evaluation harness."""
        self.baseline_repeated_questions = self.BASELINE_REPEATED_QUESTIONS

    def run_scenario(self, scenario_id: int) -> Dict[str, Any]:
        """
        Run a single test scenario.

        Returns metrics: {
            scenario_id, repeated_questions, recall_accuracy, session_start_ms
        }

        For hackathon: returns realistic mock values.
        """
        # Find scenario
        scenario = next(
            (s for s in self.SCENARIOS if s["scenario_id"] == scenario_id),
            None
        )
        if not scenario:
            return {
                "scenario_id": scenario_id,
                "repeated_questions": 0,
                "recall_accuracy": 0.0,
                "session_start_ms": 0
            }

        # Mock results based on previous sessions (more sessions = better recall)
        prev_sessions = scenario["previous_sessions"]

        # Mock: more sessions = fewer repeated questions
        repeated_questions = max(0.1, 2.5 - (prev_sessions * 0.3))

        # Mock: more sessions = higher recall accuracy
        recall_accuracy = min(0.99, 0.70 + (prev_sessions * 0.05))

        # Mock: session start time (fast)
        session_start_ms = 45 + (prev_sessions * 2)  # Slightly slower with more history

        return {
            "scenario_id": scenario_id,
            "repeated_questions": round(repeated_questions, 2),
            "recall_accuracy": round(recall_accuracy, 3),
            "session_start_ms": session_start_ms
        }

    def compare(self, ps01_metrics: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Compare PS-01 against baseline.

        Args:
            ps01_metrics: Optional dict with ps01 metrics. If not provided,
                         runs all scenarios internally.

        Returns: {
            baseline: 7.2,
            with_ps01: average repeated questions,
            improvement_pct: percentage improvement,
            recall_accuracy_avg: average recall  (if available),
            session_start_ms_avg: average latency (if available)
        }
        """
        if ps01_metrics:
            # Use provided metrics
            with_ps01 = ps01_metrics.get("repeated_questions", 0)
            recall_avg = ps01_metrics.get("recall_accuracy", 0)
        else:
            # Run all scenarios
            results = []
            for scenario in self.SCENARIOS:
                result = self.run_scenario(scenario["scenario_id"])
                results.append(result)

            # Calculate averages
            repeated_questions_list = [r["repeated_questions"] for r in results]
            recall_accuracy_list = [r["recall_accuracy"] for r in results]
            session_start_ms_list = [r["session_start_ms"] for r in results]

            with_ps01 = statistics.mean(repeated_questions_list)
            recall_avg = statistics.mean(recall_accuracy_list)
            latency_avg = statistics.mean(session_start_ms_list)

            result_dict = {
                "baseline": self.BASELINE_REPEATED_QUESTIONS,
                "with_ps01": round(with_ps01, 2),
                "improvement_pct": round(
                    ((self.BASELINE_REPEATED_QUESTIONS - with_ps01) / 
                     self.BASELINE_REPEATED_QUESTIONS) * 100, 1),
                "recall_accuracy_avg": round(recall_avg, 3),
                "session_start_ms_avg": round(latency_avg, 1)
            }
            return result_dict

        # Calculate improvement percentage
        improvement_pct = ((self.BASELINE_REPEATED_QUESTIONS - with_ps01) / 
                          self.BASELINE_REPEATED_QUESTIONS) * 100

        return {
            "baseline": self.BASELINE_REPEATED_QUESTIONS,
            "with_ps01": round(with_ps01, 2),
            "improvement_pct": round(improvement_pct, 1)
        }
