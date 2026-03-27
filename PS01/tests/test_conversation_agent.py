"""
Tests for ConversationAgent.

Tests the live chat response generation, income revision detection,
and document mention detection.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from src.core.conversation_agent import ConversationAgent


@pytest.fixture
def agent():
    """Create ConversationAgent instance for testing."""
    return ConversationAgent()


class TestConversationAgent:
    """Test suite for ConversationAgent."""

    @pytest.mark.asyncio
    async def test_respond_with_mocked_ollama(self, agent):
        """
        Test agent response generation with mocked Ollama.
        
        Scenario: Customer says "ab mera income 62,000 ho gaya"
        Expected: Agent response contains acknowledgment, income_revised detected
        """
        mock_response = {
            "message": {
                "content": "Achha, toh ab 62,000 ho gayi — yeh toh acchi baat hai!"
            }
        }
        
        with patch("ollama.chat", return_value=mock_response):
            result = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="ab mera income 62,000 ho gaya",
                briefing_summary="Previous income: 55000",
                customer_name="Rajesh"
            )
        
        assert result["agent_response"] == "Achha, toh ab 62,000 ho gayi — yeh toh acchi baat hai!"
        assert result["income_revised"] is True
        assert result["new_income_value"] == "62000"
        assert result["turn_count"] == 1
        assert len(result["facts_to_update"]) > 0

    @pytest.mark.asyncio
    async def test_income_revision_detection(self, agent):
        """Test income revision detection regex patterns."""
        
        # Test: Natural mention of new income
        mock_response = {
            "message": {
                "content": "Bilkul Rajesh ji, 62000 toh better hai — eligibility ~48 lakh hogi"
            }
        }
        
        with patch("ollama.chat", return_value=mock_response):
            result = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="mera naya income 62000 hai",
                briefing_summary="Old income: 55000",
                customer_name="Rajesh"
            )
        
        assert result["income_revised"] is True
        assert result["new_income_value"] == "62000"

    @pytest.mark.asyncio
    async def test_document_mention_detection(self, agent):
        """Test document type detection."""
        
        # Test: Payslip mentioned
        mock_response = {
            "message": {
                "content": "Great! Aapka latest payslip bhej diya — isse income verify ho jayega"
            }
        }
        
        with patch("ollama.chat", return_value=mock_response):
            result = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="maine payslip bhej diya",
                briefing_summary="Waiting for income verification",
                customer_name="Rajesh"
            )
        
        assert result["document_mentioned"] is True
        assert result["document_type"] == "payslip"

    @pytest.mark.asyncio
    async def test_conversation_history_buildup(self, agent):
        """Test that conversation history accumulates correctly."""
        
        mock_response = {
            "message": {"content": "Bilkul ji, main samjha."}
        }
        
        with patch("ollama.chat", return_value=mock_response):
            # First turn
            r1 = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="Namaskar, mujhe ghar ka loan chahiye",
                briefing_summary="New customer",
                customer_name="Rajesh"
            )
            
            # Second turn
            r2 = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="Main 55000 per month kamate hoon",
                briefing_summary="New customer",
                customer_name="Rajesh"
            )
            
            # Third turn
            r3 = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="Property Bangalore mein hai",
                briefing_summary="New customer",
                customer_name="Rajesh"
            )
        
        assert r1["turn_count"] == 1
        assert r2["turn_count"] == 2
        assert r3["turn_count"] == 3
        
        # Check history
        history = agent.get_history("S001")
        assert len(history) == 6  # 3 customer + 3 agent turns

    @pytest.mark.asyncio
    async def test_ollama_timeout_graceful_degradation(self, agent):
        """Test that agent handles Ollama timeout gracefully."""
        
        with patch("ollama.chat", side_effect=TimeoutError("Connection timed out")):
            result = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="What's my eligibility?",
                briefing_summary="Income: 55000",
                customer_name="Rajesh"
            )
        
        # Should fall back to error message
        assert "trouble" in result["agent_response"].lower() or "repeat" in result["agent_response"].lower()
        assert result["turn_count"] == 1

    def test_session_history_clear(self, agent):
        """Test clearing session history."""
        agent.history["S001"] = ["CUSTOMER: hi", "AGENT: hello"]
        
        assert len(agent.get_history("S001")) == 2
        agent.clear_session("S001")
        assert len(agent.get_history("S001")) == 0

    def test_detect_income_revision_patterns(self, agent):
        """Test various income revision patterns."""
        
        test_cases = [
            ("now my income is 62000", False, None),  # "now" not a revision keyword
            ("ab 62000 ho gaya", True, "62000"),  # "ab" + "ho gaya" = revision
            ("income 55,000 per month", False, None),  # No revision keyword
            ("62000 toh better hai", True, "62000"),  # "toh" = revision keyword
            ("₹62000 per month", False, None),  # No revision keyword
            ("income revised to 62000", True, "62000"),  # "revised" = revision keyword
            ("ab 70000 ho gayi", True, "70000"),  # "ab" + "ho gayi" = revision
        ]
        
        for response_text, expected_revised, expected_value in test_cases:
            revised, value = agent._detect_income_revision(response_text)
            assert revised == expected_revised, f"Failed for: {response_text}"
            if expected_revised:
                assert value == expected_value

    def test_detect_document_types(self, agent):
        """Test document type detection."""
        
        test_cases = [
            ("Your payslip is needed", True, "payslip"),
            ("Please provide Form 16", True, "identity_or_income_doc"),
            ("Send your property deed", True, "property_doc"),
            ("Bank statement required", True, "bank_statement"),
        ]
        
        for response_text, expected_found, expected_type in test_cases:
            found, doc_type = agent._detect_document_mention(response_text)
            assert found == expected_found, f"Failed for: {response_text}"
            if expected_found:
                assert doc_type == expected_type

    @pytest.mark.asyncio
    async def test_facts_to_update_empty_when_no_changes(self, agent):
        """Test that facts_to_update is empty when there's no income/document change."""
        
        mock_response = {
            "message": {"content": "Thank you for the information. Let me review."}
        }
        
        with patch("ollama.chat", return_value=mock_response):
            result = await agent.respond(
                session_id="S001",
                customer_id="C001",
                agent_id="AGT_A",
                customer_message="Anything else I should know?",
                briefing_summary="Income: 55000, Co-applicant: Sunita",
                customer_name="Rajesh"
            )
        
        assert result["income_revised"] is False
        assert result["document_mentioned"] is False
        assert len(result["facts_to_update"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
