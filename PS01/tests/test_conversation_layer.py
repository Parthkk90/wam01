"""
TDD: Conversation Layer Tests
- BriefingSpeechBuilder: Converts briefing dict → natural Hinglish opening
- ConversationAgent: Handles live conversation with memory + income detection

All tests MOCK ollama (never call real service).
6 tests, all RED until implementation complete.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────
# TEST 1: BriefingSpeechBuilder returns Hinglish string
# ──────────────────────────────────────────────────────────────────────
def test_briefing_speech_returns_hinglish_string():
    """
    BriefingSpeechBuilder.build_opening() must return a natural Hinglish string.
    """
    from src.core.briefing_speech import BriefingSpeechBuilder
    
    mock_briefing = {
        "customer_id": "C001",
        "customer_name": "Rajesh",
        "session_count": 2,
        "facts": [
            {
                "type": "co_applicant",
                "value": "Sunita",
                "verified": True,
                "source": "customer_verbal"
            },
            {
                "type": "property_location",
                "value": "Nashik",
                "verified": True,
                "source": "customer_verbal"
            }
        ]
    }
    
    with patch('src.core.briefing_speech.requests.post') as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Rajesh ji, namaskar! Aapne Nashik wali property ka mention kiya tha — kya documents ready hain?"
        }
        mock_post.return_value = mock_response
        
        builder = BriefingSpeechBuilder()
        result = builder.build_opening(mock_briefing)
        
        assert isinstance(result, str), "Result must be string"
        assert len(result) > 10, "Result must be non-trivial"
        assert "Rajesh" in result or "ji" in result or "namaskar" in result, "Result must contain Hinglish marker"


# ──────────────────────────────────────────────────────────────────────
# TEST 2: BriefingSpeechBuilder uses phi4-mini ONLY
# ──────────────────────────────────────────────────────────────────────
def test_briefing_speech_uses_phi4mini_only():
    """
    BriefingSpeechBuilder must call ollama with model="phi4-mini".
    NEVER tinyllama, NEVER mistral.
    """
    from src.core.briefing_speech import BriefingSpeechBuilder
    
    mock_briefing = {
        "customer_id": "C001",
        "customer_name": "Rajesh",
        "session_count": 1,
        "facts": []
    }
    
    with patch('src.core.briefing_speech.requests.post') as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {"response": "Namaskar!"}
        mock_post.return_value = mock_response
        
        builder = BriefingSpeechBuilder()
        builder.build_opening(mock_briefing)
        
        # Verify the POST call
        assert mock_post.called, "Must call ollama API"
        call_args = mock_post.call_args
        payload = call_args[1]['json']  # Get the JSON body
        
        assert payload['model'] == "phi4-mini", f"Model must be phi4-mini, got {payload['model']}"


# ──────────────────────────────────────────────────────────────────────
# TEST 3: BriefingSpeechBuilder fallback on exception
# ──────────────────────────────────────────────────────────────────────
def test_briefing_speech_fallback_on_exception():
    """
    If ollama raises exception, must return fallback string without crashing.
    Fallback must be natural Hinglish (contains "Rajesh ji" or "namaskar").
    """
    from src.core.briefing_speech import BriefingSpeechBuilder
    
    mock_briefing = {
        "customer_id": "C001",
        "customer_name": "Rajesh",
        "session_count": 1,
        "facts": []
    }
    
    with patch('src.core.briefing_speech.requests.post') as mock_post:
        mock_post.side_effect = Exception("Ollama timeout")
        
        builder = BriefingSpeechBuilder()
        result = builder.build_opening(mock_briefing)
        
        assert isinstance(result, str), "Must return string even on error"
        assert len(result) > 0, "Fallback must not be empty"
        assert "Rajesh" in result or "ji" in result, "Fallback must be Hinglish"
        # No exception should propagate
        assert True, "Exception was caught, test passed"


# ──────────────────────────────────────────────────────────────────────
# TEST 4: ConversationAgent detects income revision (55K → 62K)
# ──────────────────────────────────────────────────────────────────────
def test_conversation_agent_detects_income_revision():
    """
    ConversationAgent.respond() must detect when customer mentions new income.
    If briefing has income=55000 and customer says "62000 ho gayi",
    then result["income_revised"] must be True.
    """
    from src.core.conversation_agent import ConversationAgent
    
    mock_briefing = {
        "customer_id": "C001",
        "customer_name": "Rajesh",
        "session_count": 2,
        "facts": [
            {
                "type": "income",
                "value": "55000_INR_MONTHLY",
                "verified": True,
                "source": "customer_verbal"
            }
        ]
    }
    
    with patch('src.core.conversation_agent.requests.post') as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Achha, 62,000 ho gayi — yeh toh acchi baat hai Rajesh ji."
        }
        mock_post.return_value = mock_response
        
        agent = ConversationAgent()
        result = agent.respond(
            session_id="S001",
            customer_id="C001",
            agent_id="AGT_D",
            customer_message="mere paas ab 62000 monthly aa raha hai",
            briefing=mock_briefing
        )
        
        assert result["income_revised"] == True, "Must detect income revision"
        assert result["new_income_value"] is not None, "Must capture new income value"
        # The new value should be 62000 (extracted from message)
        assert "62" in str(result["new_income_value"]), "New income must contain 62"


# ──────────────────────────────────────────────────────────────────────
# TEST 5: ConversationAgent history limited to max 4 turns
# ──────────────────────────────────────────────────────────────────────
def test_conversation_agent_history_max_4_turns():
    """
    ConversationAgent.get_history() must never exceed 4 turns per session.
    4 turns = 8 entries (customer + agent response × 4).
    After turn 5, oldest turn 1 must be dropped.
    """
    from src.core.conversation_agent import ConversationAgent
    
    mock_briefing = {
        "customer_id": "C001",
        "customer_name": "Rajesh",
        "session_count": 1,
        "facts": []
    }
    
    with patch('src.core.conversation_agent.requests.post') as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Bilkul, understood."
        }
        mock_post.return_value = mock_response
        
        agent = ConversationAgent()
        
        # Make 6 turns (should trim to 4)
        for i in range(6):
            agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_D",
                customer_message=f"Question {i+1}?",
                briefing=mock_briefing
            )
        
        history = agent.get_history("S001")
        assert len(history) <= 8, f"History exceeded 4 turns (8 entries), has {len(history)}"


# ──────────────────────────────────────────────────────────────────────
# TEST 6: ConversationAgent never crashes (robust fallback)
# ──────────────────────────────────────────────────────────────────────
def test_conversation_agent_never_crashes():
    """
    Even if ollama crashes, ConversationAgent.respond() must return valid dict.
    Must have: agent_response, income_revised, new_income_value, turn_count
    Must NOT propagate exception.
    """
    from src.core.conversation_agent import ConversationAgent
    
    mock_briefing = {
        "customer_id": "C001",
        "customer_name": "Rajesh",
        "session_count": 1,
        "facts": []
    }
    
    with patch('src.core.conversation_agent.requests.post') as mock_post:
        mock_post.side_effect = ConnectionError("Ollama down")
        
        agent = ConversationAgent()
        result = agent.respond(
            session_id="S001",
            customer_id="C001",
            agent_id="AGT_D",
            customer_message="hello",
            briefing=mock_briefing
        )
        
        # Must return valid dict
        assert isinstance(result, dict), "Must return dict on error"
        assert "agent_response" in result, "Must have agent_response key"
        assert "income_revised" in result, "Must have income_revised key"
        assert "new_income_value" in result, "Must have new_income_value key"
        assert "turn_count" in result, "Must have turn_count key"
        
        # Must have fallback values
        assert isinstance(result["agent_response"], str), "agent_response must be string"
        assert len(result["agent_response"]) > 0, "Fallback response must not be empty"
        assert result["income_revised"] == False, "income_revised must be False on error"
        assert result["new_income_value"] is None, "new_income_value must be None on error"
        
        # No exception should propagate - if we got here, test passed


# ──────────────────────────────────────────────────────────────────────
# PYTEST CONFIGURATION
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
