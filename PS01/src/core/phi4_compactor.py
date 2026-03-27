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

        response = ollama.chat(
            model='phi4-mini',
            messages=[{'role': 'user', 'content': prompt}],
            stream=False
        )

        summary_text = response['message']['content']
        try:
            summary_json = json.loads(summary_text)
        except json.JSONDecodeError:
            # Phi-4-Mini might not output pure JSON
            summary_json = {"raw": summary_text, "parsed": False}

        # Write summary to Redis cache if available
        if redis_cache is not None and customer_id:
            summary_json_str = json.dumps(summary_json)
            await redis_cache.set_summary(customer_id, summary_json_str)

        return summary_json
