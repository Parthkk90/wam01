"""
BriefingSpeechBuilder: Converts structured briefing dict → natural Hinglish opening.

READ PATH step 4: When a new agent picks up a session, this generates the
natural opening sentence that makes the customer feel remembered.

Model: phi4-mini ONLY
Timeout: 30s
Temperature: 0.7 (higher for natural speech variation)
"""

import os
import requests
import logging
from typing import Optional, Dict, List
import re

logger = logging.getLogger(__name__)


class BriefingSpeechBuilder:
    """
    Generates natural Hinglish opening sentences from briefing dict.
    
    The judge listens to this sentence. It must sound like the agent
    was actually listening to previous calls, not reading a database.
    """
    
    def __init__(self, ollama_api: str = None):
        """
        Initialize with Ollama API endpoint.
        Default: read from OLLAMA_API env or fallback to localhost:11434
        """
        if ollama_api is None:
            ollama_api = os.getenv("OLLAMA_API", "http://localhost:11434")
        self.ollama_api = ollama_api
        self.model = "phi4-mini"  # IMMUTABLE - never change
    
    def build_opening(self, briefing: Dict) -> str:
        """
        Convert { customer_name, session_count, facts } → natural opening sentence.
        
        Args:
            briefing: { customer_id, customer_name, session_count, facts: [{...}] }
        
        Returns:
            Natural Hinglish string, max 40 words.
            Falls back to template if ollama fails.
        """
        try:
            preferred_language = str(briefing.get("preferred_language", "hindi")).lower()
            grounded_opening = self._build_grounded_opening(briefing)
            if grounded_opening:
                return grounded_opening

            # Step 1: Extract briefing fields
            customer_name = briefing.get("customer_id", "Customer")
            session_count = briefing.get("session_count", 1)
            facts = briefing.get("facts", [])

            # Never let the model invent prior context for first-session customers.
            if session_count <= 0 or not facts:
                if preferred_language == "english":
                    return f"Hello {customer_name}, let's start your home loan process today."
                return f"Namaste {customer_name}, chaliye aaj aapka home loan process start karte hain."
            
            # Step 2: Summarize facts (max 5, most recent first)
            facts_summary = self._facts_to_summary(facts)
            
            # Step 3: Build prompt
            prompt_text = self._build_prompt(
                customer_name=customer_name,
                session_count=session_count,
                facts_summary=facts_summary,
                preferred_language=preferred_language,
            )
            
            # Step 4: Call ollama
            response = requests.post(
                f"{self.ollama_api}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt_text,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_ctx": 1024,
                        "num_predict": 80
                    }
                },
                timeout=30
            )
            response.raise_for_status()
            
            # Step 5: Extract and clean response
            response_text = response.json().get("response", "").strip()
            if not response_text:
                return self._fallback_opening(briefing)
            
            # Remove quotes if wrapped
            if response_text.startswith('"') and response_text.endswith('"'):
                response_text = response_text[1:-1].strip()
            
            return response_text
            
        except (requests.Timeout, requests.ConnectionError, Exception) as e:
            logger.debug(f"BriefingSpeechBuilder error: {e}")
            return self._fallback_opening(briefing)

    def _build_grounded_opening(self, briefing: Dict) -> Optional[str]:
        """Construct a deterministic, factual opening from retrieved recall fields."""
        recall = briefing.get("deterministic_recall") or {}
        if not recall:
            return None

        customer_name = briefing.get("customer_id", "customer")
        preferred_language = str(briefing.get("preferred_language", "hindi")).lower()
        day = recall.get("last_discussed_day")
        day_ref = f"last {day}" if day else "last time"

        co_name = (recall.get("co_applicant_name") or {}).get("value")
        co_income = (recall.get("co_applicant_income") or {}).get("value")
        income = (recall.get("latest_income") or {}).get("value")

        if preferred_language == "english":
            if co_name and co_income:
                return (
                    f"Hello {customer_name}, {day_ref} you mentioned co-applicant {co_name}. "
                    f"Should I include income {co_income} in this calculation?"
                )
            if co_name:
                return (
                    f"Hello {customer_name}, {day_ref} you mentioned co-applicant {co_name}. "
                    "Should I include their income as well?"
                )
            if income:
                return (
                    f"Hello {customer_name}, {day_ref} you shared income {income}. "
                    "Should we continue with this as the base amount?"
                )

        if co_name and co_income:
            return (
                f"Namaste {customer_name}, {day_ref} aapne co-applicant {co_name} mention kiya tha, "
                f"kya main unki income {co_income} bhi factor karun?"
            )
        if co_name:
            return (
                f"Namaste {customer_name}, {day_ref} aapne co-applicant {co_name} mention kiya tha, "
                "kya main unki income bhi factor karun?"
            )
        if income:
            return (
                f"Namaste {customer_name}, {day_ref} aapne income {income} batayi thi, "
                "kya hum isi base par aage badhein?"
            )

        return None
    
    def _build_prompt(self, customer_name: str, session_count: int,
                      facts_summary: str, preferred_language: str = "hindi") -> str:
        """Build the exact prompt for phi4-mini."""
        language_rule = (
            "- Write ONLY in English. Do not switch to Hindi or Hinglish."
            if preferred_language == "english"
            else "- Use Hinglish naturally (mix Hindi + English, Pune banker style)"
        )
        prompt = f"""You are a cooperative bank loan officer in Pune, India.
You are calling a customer you have spoken to before.
You have notes from previous calls:

Customer: {customer_name}
Previous sessions: {session_count}
Key facts known:
{facts_summary}

Write your opening sentence when the call connects.

Rules:
- Sound like YOU personally remember — not like you read a file
{language_rule}
- Reference ONE specific detail the customer told you before
- Use time naturally: "last time", "pichle baar", "Tuesday ko"
- Ask ONE soft follow-up showing you were paying attention
- Maximum 40 words
- NEVER say "our records show" or "as per our system"
- NEVER list multiple facts — pick the most emotionally relevant one
- If income was recently revised, reference the revision naturally

Your opening sentence only:"""
        return prompt
    
    def _facts_to_summary(self, facts: List[Dict]) -> str:
        """
        Convert fact list to concise bullet summary.
        
        Takes max 5 facts, sorted by verified first + recency.
        Format: "- {type}: {value} ({source}, {'verified'|'unverified'})"
        Max total 200 chars.
        """
        if not facts:
            return "No prior facts recorded yet (first session)"
        
        # Sort: verified first, then by recency (assume list order is recent first)
        sorted_facts = sorted(facts, key=lambda f: (not f.get("verified", False), facts.index(f)))
        
        lines = []
        for fact in sorted_facts[:5]:  # Max 5 facts
            fact_type = fact.get("type", "unknown")
            value = fact.get("value", "")
            source = fact.get("source", "")
            verified = "verified" if fact.get("verified", False) else "unverified"
            
            line = f"- {fact_type}: {value} ({source}, {verified})"
            lines.append(line)
        
        summary = "\n".join(lines)
        if len(summary) > 200:
            # Truncate to 200 chars
            summary = summary[:200] + "..."
        
        return summary
    
    def _fallback_opening(self, briefing: Optional[Dict] = None) -> str:
        """
        Fallback Hinglish opening if ollama fails.
        Must be natural and show context awareness.
        """
        preferred_language = str((briefing or {}).get("preferred_language", "hindi")).lower()
        if preferred_language == "english":
            return "Hello, welcome back. Shall we continue your home loan process from where we left off?"
        return (
            "Rajesh ji, namaskar! Aapne pichle baar home loan ke baare "
            "mein baat ki thi — kya documents ready ho gayi hain ab?"
        )
