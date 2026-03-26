"""
Deepgram STT stub — placeholder for real-time speech-to-text.
Currently: no real implementation. Returns placeholder transcripts.
"""

from typing import Optional, AsyncIterator, Dict, Any


class DeepgramClient:
    """
    Deepgram STT client stub.
    Real implementation TBD when voice input is finalized.
    """

    def __init__(self, api_key: str = "", **kwargs):
        """Initialize Deepgram client."""
        self.api_key = api_key

    async def stream_transcribe(
        self,
        audio_chunk_generator: Optional[AsyncIterator[bytes]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream transcription from audio chunks.
        Yields: {transcript, language, confidence}
        """
        return
        # Stub: do not yield anything yet
        yield  # pragma: no cover

    async def transcribe(self, audio_file: str) -> Dict[str, Any]:
        """Transcribe a single audio file."""
        return {
            "transcript": "",
            "language": "hi",
            "confidence": 0.0
        }
