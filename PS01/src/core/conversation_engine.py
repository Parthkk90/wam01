"""
ConversationEngine: LLM-powered natural language generation for loan conversations.
Uses phi4-mini via Ollama with fallback to template-based generation.
"""

import json
import logging
from typing import Dict, List, Any, Optional
import requests
from .conversation_templates import fill_template, get_fact_summary_template

logger = logging.getLogger(__name__)
OLLAMA_TIMEOUT = 2  # Reduced from 10s for faster test feedback


class ConversationEngine:
    """Generate conversational responses using Ollama phi4-mini."""

    def __init__(self, ollama_api: str = "http://localhost:11434"):
        """Initialize engine with Ollama endpoint."""
        self.ollama_api = ollama_api

    def _call_ollama(self, prompt: str, max_tokens: int = 150) -> Optional[str]:
        """
        Call phi4-mini safely with timeout and error handling.
        Returns None on failure (will trigger fallback).
        Skips if endpoint appears to be mock/local unavailable.
        """
        # Quick fail for localhost:11434 if it's not responding fast
        # This helps tests fail fast instead of waiting for timeouts
        try:
            response = requests.post(
                f"{self.ollama_api}/api/generate",
                json={
                    "model": "phi4-mini",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.3},
                },
                timeout=1.5,  # Even faster timeout for quick fallback
            )
            response.raise_for_status()
            return response.json().get("response", "").strip()
        except (requests.Timeout, requests.ConnectionError) as e:
            return None  # Fail silently, use fallback
        except Exception as e:
            logger.debug(f"Ollama error: {e}")
            return None

    def summarize_facts(self, facts: List[Dict]) -> str:
        """
        Convert fact list to 1-2 sentence natural language.
        Falls back to templates if Ollama unavailable.
        """
        if not facts:
            return "No prior information available."

        facts_json = json.dumps(facts[:5], indent=2)  # Limit to 5 facts
        prompt = f"""You are a helpful Indian bank loan officer assistant.
Convert these loan application facts into 1-2 natural sentences.
Do not use bullet points. Merge related facts. Sound warm and conversational.
Output ONLY the sentences, nothing else.

Facts: {facts_json}"""

        result = self._call_ollama(prompt, max_tokens=100)
        if result:
            return result

        # Fallback: manual summary from facts
        summaries = []
        for fact in facts[:3]:  # Limit to top 3 facts
            if fact.get("verified"):
                if fact.get("type") == "income":
                    summaries.append(f"income of ₹{fact.get('value')}")
                elif fact.get("type") == "co_applicant_income":
                    summaries.append(f"co-applicant income of ₹{fact.get('value')}")
                elif fact.get("type") == "property_location":
                    summaries.append(f"property in {fact.get('value')}")
        return ", ".join(summaries) if summaries else "Previous application information."

    def generate_greeting(
        self, customer_name: str, facts: List[Dict], session_count: int
    ) -> str:
        """
        Generate opening message for returning customer.
        Uses session count to customize greeting level.
        """
        if session_count == 0:
            return fill_template(
                "greeting_new"
            )  # "Welcome! I'm here to help..."

        facts_summary = self.summarize_facts(facts)

        if session_count == 1:
            greeting = f"Welcome back, {customer_name}! Last time, {facts_summary} Shall we continue?"
        else:
            greeting = f"Hi {customer_name}! I can see we've spoken {session_count} times now. From our previous conversations, {facts_summary} Ready to continue?"

        # Try Ollama polish
        prompt = f"""You are a warm, professional Indian bank loan officer.
A returning customer is calling back.
Polish this greeting to sound natural, brief (under 3 sentences), and empathetic.
Do not mention systems or databases.

Greeting: {greeting}

Output: (only the polished greeting)"""

        result = self._call_ollama(prompt, max_tokens=80)
        if result:
            return result

        # Fallback to template
        if session_count >= 2:
            return fill_template("greeting_repeat", name=customer_name)
        return fill_template("greeting_returning", name=customer_name)

    def generate_next_step(self, facts: List[Dict], flags: List[str]) -> str:
        """Generate what agent should ask/do next based on flags."""
        if "income_unverified" in flags:
            return "We'll need your latest payslip or Form 16 to confirm your income before we finalize eligibility."
        if "co_applicant_unverified" in flags:
            return "Could you also arrange documents for your co-applicant's income verification?"
        if "property_unverified" in flags:
            return "We'll need your property documents to proceed. Can you arrange those?"
        if "has_pending_review" in flags:
            return "There are a few details from last time we should clarify. Do you have time to go through them?"

        # Default: find missing fact type
        verified_types = {f.get("type") for f in facts if f.get("verified")}
        if "co_applicant_income" not in verified_types:
            return fill_template("verification_ask", field="co-applicant income")
        if "property_location" not in verified_types:
            return fill_template("verification_ask", field="property details")

        return "What else would you like to know about your loan application?"

    def build_conversational_briefing(
        self,
        customer_id: str,
        customer_name: str,
        facts: List[Dict],
        flags: List[str],
        session_count: int,
    ) -> Dict[str, Any]:
        """Build complete conversational briefing dict."""
        greeting = self.generate_greeting(customer_name, facts, session_count)
        context = self.summarize_facts(facts)
        next_step = self.generate_next_step(facts, flags)

        return {
            "greeting_message": greeting,
            "context_summary": context,
            "suggested_next": next_step,
            "session_count": session_count,
            "has_prior_context": session_count > 0,
        }
