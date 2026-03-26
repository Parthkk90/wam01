# src/preprocessing/tokenizer.py
import re
import hashlib
from typing import Dict, List, Tuple

# Regex patterns for banking entity recognition
PAN_REGEX = r"[A-Z]{5}[0-9]{4}[A-Z]"
AADHAAR_REGEX = r"[0-9]{4}[0-9]{4}[0-9]{4}"
PHONE_REGEX = r"\+?91[6-9]\d{9}"


class BankingTokenizer:
    """Tokenize banking transcripts: replace PII with tokens."""

    def __init__(self):
        """Initialize tokenizer with PII pattern mapping."""
        self.token_map = {}  # { "ABCDE1234F": "[TOKEN:PAN:hash123]" }

    def tokenize(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Replace PII (PAN, Aadhaar, phone, income) with tokens.
        Returns: (tokenized_text, {original: token_replacement})
        """
        tokenized = text
        token_map = {}

        # Replace PAN numbers
        for match in re.finditer(PAN_REGEX, text):
            pan = match.group(0)
            if pan not in token_map:
                token_hash = hashlib.md5(pan.encode()).hexdigest()[:8]
                token_replacement = f"[TOKEN:PAN:{token_hash}]"
                token_map[pan] = token_replacement
                tokenized = tokenized.replace(pan, token_replacement)

        # Replace Aadhaar numbers
        for match in re.finditer(AADHAAR_REGEX, text):
            aadhaar = match.group(0)
            if aadhaar not in token_map:
                token_hash = hashlib.md5(aadhaar.encode()).hexdigest()[:8]
                token_replacement = f"[TOKEN:AADHAAR:{token_hash}]"
                token_map[aadhaar] = token_replacement
                tokenized = tokenized.replace(aadhaar, token_replacement)

        # Replace phone numbers
        for match in re.finditer(PHONE_REGEX, text):
            phone = match.group(0)
            if phone not in token_map:
                token_hash = hashlib.md5(phone.encode()).hexdigest()[:8]
                token_replacement = f"[TOKEN:PHONE:{token_hash}]"
                token_map[phone] = token_replacement
                tokenized = tokenized.replace(phone, token_replacement)

        self.token_map = token_map
        return tokenized, token_map

    def detokenize(self, text: str, mapping: Dict[str, str]) -> str:
        """Reverse mapping (for demo only; never in real output)."""
        reverse = {v: k for k, v in mapping.items()}
        for token, original in reverse.items():
            text = text.replace(token, original)
        return text
