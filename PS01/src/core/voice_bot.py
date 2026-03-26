"""
Voice bot stub — placeholder for future voice interaction.
Currently: no real implementation. Returns empty responses.
"""

from typing import Optional, Dict, Any


class VoiceBot:
    """
    Voice bot stub.
    Loads customer context and generates responses.
    Real implementation TBD when voice input is decided.
    """

    def __init__(self, customer_id: str = "", memory: Optional[Any] = None, **kwargs):
        """Initialize with customer ID and optional memory."""
        self.customer_id = customer_id
        self.memory = memory
        self.customer_context = {}
        self.conversation_history = []
        self.system_prompt = ""

    async def load_customer_context(self, customer_id: str) -> None:
        """Load customer memory from cache/db."""
        self.customer_id = customer_id
        self.customer_context = {}

    async def respond(self, user_input: str) -> str:
        """Generate response to user input."""
        return ""

    def get_system_prompt(self) -> str:
        """Get system prompt for voice bot."""
        return ""
