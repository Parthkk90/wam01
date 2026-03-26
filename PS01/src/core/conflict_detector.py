from typing import List, Dict
from .adversarial_guard import AdversarialGuard


class ConflictDetector:
    @staticmethod
    def detect(existing_facts: List[Dict], new_facts: List[Dict]) -> List[Dict]:
        """Find contradictions, annotating with adversarial guard results."""
        guard = AdversarialGuard()
        conflicts = []
        for new_fact in new_facts:
            for existing in existing_facts:
                if new_fact.get('type') == existing.get('type') and \
                   new_fact.get('value') != existing.get('value'):
                    conflict = {
                        "type": new_fact.get('type'),
                        "old_value": existing.get('value'),
                        "new_value": new_fact.get('value'),
                        "supersedes": existing.get('fact_id')
                    }
                    # Run adversarial check if both values are numeric
                    old_val = existing.get('value')
                    new_val = new_fact.get('value')
                    if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                        guard_result = guard.check(new_fact.get('type', ''), float(old_val), float(new_val))
                        conflict["suspicious"] = guard_result["suspicious"]
                        conflict["review_required"] = guard_result["suspicious"]
                        conflict["reason"] = guard_result["reason"]
                        conflict["pct_change"] = guard_result["pct_change"]
                    else:
                        conflict["suspicious"] = False
                        conflict["review_required"] = False
                        conflict["reason"] = "non-numeric comparison"
                        conflict["pct_change"] = 0.0
                    conflicts.append(conflict)
        return conflicts
