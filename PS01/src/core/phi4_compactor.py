import ollama
import json
from typing import List, Dict, Any, Optional
from ..infra import RedisCache

COMPACTOR_PROMPT_TEMPLATE = """
You are a memory compactor for a banking system.
You receive raw facts from a loan officer session.
Your job: compress them into a minimal fact sheet for efficient storage.

Rules:
- If income appears twice, keep only the latest value
- Mark verified=true only if source is "document_parsed"
- Merge co-applicant facts into one record
- Remove contradictions by keeping the most recent fact
- Output ONLY valid JSON, no explanation, no markdown

Input facts:
{facts_json}

Output format (ONLY JSON, nothing else):
{{
  "customer_id": "{customer_id}",
  "as_of_session": "{session_timestamp}",
  "facts": [
    {{"type": "income", "value": "55000", "verified": false, "source": "customer_verbal"}},
    {{"type": "co_applicant_name", "value": "Sunita", "verified": false, "source": "customer_verbal"}},
    {{"type": "co_applicant_income", "value": "30000", "verified": false, "source": "customer_verbal"}}
  ],
  "verified_count": 0,
  "unverified_count": 3
}}
"""


class Phi4Compactor:
    def __init__(self, ollama_api: str = "http://localhost:11434"):
        self.ollama_api = ollama_api

    async def compact(
        self,
        facts: List[Dict],
        redis_cache: Optional[RedisCache] = None,
        bank_id: str = "",
        customer_id: str = "",
    ) -> Dict[str, Any]:
        """Compactor prompt to Phi-4-Mini"""
        from datetime import datetime, timezone
        session_timestamp = datetime.now(timezone.utc).isoformat()
        
        prompt = COMPACTOR_PROMPT_TEMPLATE.format(
            facts_json=json.dumps(facts, indent=2),
            customer_id=customer_id or "unknown",
            session_timestamp=session_timestamp
        )

        summary_text = ""
        try:
            response = ollama.chat(
                model='phi4-mini',
                messages=[{'role': 'user', 'content': prompt}],
                stream=False
            )
            summary_text = response['message']['content']
            summary_json = json.loads(summary_text)
            summary_json["parsed"] = True
        except Exception:
            summary_json = self._deterministic_compact(
                facts=facts,
                customer_id=customer_id,
                session_timestamp=session_timestamp,
            )
            summary_json["parsed"] = False
            summary_json["raw"] = summary_text

        # Write summary to Redis cache if available
        if redis_cache is not None and customer_id:
            summary_json_str = json.dumps(summary_json)
            if hasattr(redis_cache, "set_summary"):
                await redis_cache.set_summary(customer_id, summary_json_str)
            else:
                await redis_cache.set(f"summary:{customer_id}", summary_json_str, ex=14400)

        return summary_json

    def _deterministic_compact(
        self,
        facts: List[Dict],
        customer_id: str,
        session_timestamp: str,
    ) -> Dict[str, Any]:
        """Deterministic fallback compaction when model output is invalid/unavailable."""
        latest_by_type: Dict[str, Dict[str, Any]] = {}
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            f_type = str(fact.get("type", "unknown"))
            latest_by_type[f_type] = {
                "type": f_type,
                "value": fact.get("value"),
                "verified": bool(fact.get("verified", False)),
                "source": fact.get("source", "unknown"),
            }

        compacted_facts = list(latest_by_type.values())
        verified_count = sum(1 for f in compacted_facts if f.get("verified"))
        unverified_count = len(compacted_facts) - verified_count

        summary_lines = [f"{f['type']}: {f.get('value')}" for f in compacted_facts[:6]]
        summary_text = "; ".join(summary_lines) if summary_lines else "No facts captured"

        return {
            "customer_id": customer_id or "unknown",
            "as_of_session": session_timestamp,
            "facts": compacted_facts,
            "verified_count": verified_count,
            "unverified_count": unverified_count,
            "summary_text": summary_text,
        }
