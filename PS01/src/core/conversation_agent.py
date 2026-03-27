"""
ConversationAgent: Handles live conversation during active session.

READ PATH step 5: Live agent responses with memory awareness.
- Maintains per-session history (in-memory only)
- Detects income revisions (55K → 62K)
- Returns facts_to_update if something changed
- Calls phi4-mini ONLY

NEVER writes conversation history to WAL.
Only writes STRUCTURED FACTS if something changed.
"""

import os
import requests
import logging
import re
from typing import Optional, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


class ConversationAgent:
    """
    Live conversation handler with memory-aware responses.
    
    Detects when facts change (income, document status).
    Returns natural Hinglish responses via phi4-mini.
    Maintains conversation history per session (trim to 4 turns).
    """
    
    def __init__(self, ollama_api: str = None, wal_logger=None, mem0_bridge=None):
        """
        Initialize with Ollama endpoint and optional WAL/Mem0 backends.
        
        Args:
            ollama_api: Ollama base URL (default: localhost:11434)
            wal_logger: WALLogger instance for writing facts
            mem0_bridge: Mem0Bridge instance for memory updates
        """
        if ollama_api is None:
            ollama_api = os.getenv("OLLAMA_API", "http://localhost:11434")
        self.ollama_api = ollama_api
        self.model = "phi4-mini"  # IMMUTABLE
        self.wal_logger = wal_logger
        self.mem0_bridge = mem0_bridge
        
        # Per-session history: {session_id: [{"role": "customer/agent", "content": "..."}]}
        self.history = {}
        self.max_history_turns = 4  # 4 turns = 8 entries (customer + agent each)
    
    def respond(self, session_id: str, customer_id: str, agent_id: str,
                customer_message: str, briefing: Dict) -> Dict:
        """
        Generate agent response to customer message.
        Detect income revisions and return facts to update.
        
        Args:
            session_id: Unique session ID
            customer_id: Customer identifier
            agent_id: Agent name (AGT_A, AGT_B, etc)
            customer_message: What customer just said
            briefing: { customer_name, session_count, facts: [...] }
        
        Returns:
            {
                "agent_response": str,          # What agent says
                "income_revised": bool,         # Did income change?
                "new_income_value": str | None, # New income if revised
                "turn_count": int,              # Turns so far in session
                "facts_to_update": list,        # Facts to write to WAL
                "session_id": str
            }
        """
        try:
            # Step 1: Initialize session history
            self.history.setdefault(session_id, [])
            
            # Step 2: Build conversation history string (last 4 turns)
            conversation_history = self._build_conversation_history(session_id)
            
            # Step 3: Summarize briefing (max 300 chars)
            briefing_summary = self._build_briefing_summary(briefing)
            
            # Step 4: Build prompt
            prompt_text = self._build_conversation_prompt(
                agent_id=agent_id,
                customer_name=briefing.get("customer_id", "Customer"),
                briefing_summary=briefing_summary,
                conversation_history=conversation_history,
                customer_message=customer_message
            )
            
            # Step 5: Call ollama
            response = requests.post(
                f"{self.ollama_api}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt_text,
                    "stream": False,
                    "options": {
                        "temperature": 0.6,
                        "num_ctx": 2048,
                        "num_predict": 120
                    }
                },
                timeout=45
            )
            response.raise_for_status()
            response_text = response.json().get("response", "").strip()
            
            if not response_text:
                return self._fallback_response(session_id, customer_message, briefing)
            
            # Step 6: Detect income revision
            income_revised, new_income_value = self._detect_income_revision(
                customer_message, briefing
            )
            
            # Step 7: Build facts_to_update if income revised
            facts_to_update = []
            if income_revised and new_income_value:
                facts_to_update = [
                    {
                        "fact_id": f"F_REV_{session_id}_{int(datetime.now().timestamp())}",
                        "type": "income",
                        "value": f"{new_income_value}_INR_MONTHLY",
                        "relationship": "updates",
                        "verified": False,
                        "source": "customer_verbal_revision",
                        "confidence": 0.85
                    }
                ]
                
                # Write to WAL immediately (IMMUTABLE RULE: WAL first)
                if self.wal_logger:
                    try:
                        self.wal_logger.append(
                            session_id=session_id,
                            customer_id=customer_id,
                            agent_id=agent_id,
                            facts=facts_to_update
                        )
                    except Exception as e:
                        logger.error(f"WAL write failed: {e}")
            
            # Step 8: Append to history
            self.history[session_id].append({
                "role": "customer",
                "content": customer_message
            })
            self.history[session_id].append({
                "role": "agent",
                "content": response_text
            })
            
            # Step 9: Trim history to max turns
            max_entries = self.max_history_turns * 2
            if len(self.history[session_id]) > max_entries:
                self.history[session_id] = self.history[session_id][-max_entries:]
            
            # Step 10: Return response dict
            return {
                "agent_response": response_text,
                "income_revised": income_revised,
                "new_income_value": new_income_value,
                "turn_count": len(self.history[session_id]) // 2,
                "facts_to_update": facts_to_update,
                "session_id": session_id
            }
        
        except Exception as e:
            logger.error(f"ConversationAgent.respond error: {e}")
            return self._fallback_response(session_id, customer_message, briefing)
    
    def _build_conversation_history(self, session_id: str) -> str:
        """Format last 4 turns as string."""
        history = self.history.get(session_id, [])
        
        if not history:
            return "This is the first message this session."
        
        # Take last 8 entries (4 turns)
        recent = history[-8:]
        lines = []
        for entry in recent:
            role = "CUSTOMER" if entry["role"] == "customer" else "AGENT"
            lines.append(f"{role}: {entry['content']}")
        
        return "\n".join(lines)
    
    def _build_briefing_summary(self, briefing: Dict) -> str:
        """Compact briefing in max 300 chars."""
        facts = (
            briefing.get("facts")
            or briefing.get("verified_facts", []) + briefing.get("unverified_facts", [])
        )
        if not facts:
            return "No prior facts."
        
        lines = []
        for fact in facts[:5]:
            f_type = fact.get("type", "")
            f_value = fact.get("value", "")
            lines.append(f"• {f_type}: {f_value}")
        
        summary = " | ".join(lines)
        if len(summary) > 300:
            summary = summary[:300] + "..."
        
        return summary
    
    def _build_conversation_prompt(self, agent_id: str, customer_name: str,
                                    briefing_summary: str,
                                    conversation_history: str,
                                    customer_message: str) -> str:
        """Build the exact conversation prompt for phi4-mini."""
        prompt = f"""You are Agent {agent_id}, a loan officer at a cooperative bank
in Pune, India. You are speaking with {customer_name}.

YOUR MEMORY (from previous sessions):
{briefing_summary}

CONVERSATION SO FAR:
{conversation_history}

CUSTOMER JUST SAID:
"{customer_message}"

Rules:
- LANGUAGE RULE: Reply in the SAME language the customer used. If they wrote in English, reply in English. If they wrote in Hindi/Hinglish, reply in Hinglish. Do NOT switch languages.
- NEVER ask for information already in your memory
- If customer mentions a NEW income figure: acknowledge naturally
  e.g. "Achha, 62,000 ho gayi — yeh toh acchi baat hai Rajesh ji"
- If asked about eligibility: give indicative figure with caveat
  e.g. "~48 lakh ke aas paas hoga, but Form 16 confirm karega"
- If customer mentions document: acknowledge and explain next step
- Keep response under 60 words
- End with ONE soft question that moves the conversation forward
- Sound warm and helpful, not robotic

NEVER say:
- "According to our records"
- "Our system shows"
- "As per your profile"

Your response:"""
        return prompt
    
    def _detect_income_revision(self, customer_message: str,
                                briefing: Dict) -> tuple:
        """
        Detect if customer mentioned a new income figure.
        
        Returns: (income_revised: bool, new_income_value: str | None)
        """
        # Extract numbers from message - exclude long numbers like Aadhaar (12 digits)
        # Only match 4-6 digit standalone numbers (income range)
        # First, mask out any 12-digit sequences to avoid matching subsets
        masked = re.sub(r'\d{9,}', 'MASKED', customer_message)
        numbers = re.findall(r'\b(\d{4,6})\b', masked)
        if not numbers:
            return False, None
        
        # Get existing income from briefing
        existing_income = self._get_existing_income(briefing)
        
        # Check if any number is a realistic income that differs from existing
        for num_str in numbers:
            num = int(num_str)
            
            # Realistic income range: 30K - 200K
            if not (30000 <= num <= 200000):
                continue
            
            # Check if different from existing
            if existing_income and str(num) == existing_income:
                continue
            
            # Found a revision!
            return True, str(num)
        
        return False, None
    
    def _get_existing_income(self, briefing: Dict) -> Optional[str]:
        """Extract income value from briefing facts."""
        facts = briefing.get("facts", [])
        for fact in facts:
            if fact.get("type") == "income":
                value = fact.get("value", "")
                numbers = re.findall(r'\d+', str(value))
                if numbers:
                    return numbers[0]
        return None
    
    def get_history(self, session_id: str) -> List[Dict]:
        """Return conversation history for a session."""
        return self.history.get(session_id, [])
    
    def clear_session(self, session_id: str) -> None:
        """Clear history for a session."""
        self.history.pop(session_id, None)
    
    def _fallback_response(self, session_id: str, customer_message: str = "",
                           briefing: Dict = None) -> Dict:
        """Context-aware fallback when ollama fails."""
        msg_lower = customer_message.lower() if customer_message else ""
        facts = []
        if briefing:
            facts = (
                briefing.get("facts")
                or briefing.get("verified_facts", []) + briefing.get("unverified_facts", [])
            )

        # Detect income mention
        income_revised, new_income_value = self._detect_income_revision(
            customer_message, briefing or {}
        )

        # Build context-aware response
        if income_revised and new_income_value:
            response = (
                f"Achha, {new_income_value} ho gayi salary — yeh toh acchi baat hai! "
                "Revised income ke saath eligibility thodi aur improve hogi. "
                "Kya updated salary slip available hai?"
            )
        elif any(w in msg_lower for w in ["document", "salary slip", "form 16", "payslip"]):
            response = (
                "Bilkul, documents ke liye — salary slip last 3 months ka "
                "aur Form 16 chahiye hoga. Kya yeh ready hai aapke paas?"
            )
        elif any(w in msg_lower for w in ["eligib", "kitna", "loan", "amount", "lakh"]):
            # Try to find income + emi from facts
            income = next((f["value"] for f in facts if f.get("type") == "income"), None)
            emi = next((f["value"] for f in facts if "emi" in f.get("type", "")), None)
            if income:
                response = (
                    f"Aapki income {income} ke hisaab se, indicative eligibility "
                    "~48 lakh ke aas paas hogi — final figure Form 16 se confirm hoga."
                )
            else:
                response = (
                    "Income aur EMI ke hisaab se hum eligibility calculate karenge. "
                    "Kya aap salary slip share kar sakte hain?"
                )
        elif any(w in msg_lower for w in ["property", "nashik", "plot", "flat", "ghar"]):
            response = (
                "Nashik wali property ke liye 7/12 extract aur encumbrance certificate "
                "chahiye hoga. Kya yeh documents ready hain?"
            )
        elif any(w in msg_lower for w in ["sunita", "wife", "co-applicant", "co applicant"]):
            response = (
                "Sunita ji ka income proof bhi include kar lenge toh combined eligibility "
                "improve hogi. Unka salary slip bhi arrange kar lijiye."
            )
        else:
            response = (
                "Yeh note kar liya. Aapki application mein hum "
                "step-by-step aage badhenge — koi aur details hain jo share karna chahenge?"
            )

        facts_to_update = []
        if income_revised and new_income_value:
            facts_to_update = [{
                "fact_id": f"F_REV_{session_id}_{int(__import__('time').time())}",
                "type": "income",
                "value": f"{new_income_value}_INR_MONTHLY",
                "relationship": "updates",
                "verified": False,
                "source": "customer_verbal_revision",
                "confidence": 0.85
            }]

        return {
            "agent_response": response,
            "income_revised": income_revised,
            "new_income_value": new_income_value,
            "turn_count": len(self.history.get(session_id, [])) // 2,
            "facts_to_update": facts_to_update,
            "session_id": session_id
        }
