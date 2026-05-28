import re
import logging

logger = logging.getLogger("agentops.security.redaction")

class PIIRedactor:
    """
    Personally Identifiable Information (PII) Redactor.
    Scans and filters context payloads going to external LLM providers,
    ensuring compliance and preventing accidental data leakage.
    """
    def __init__(self):
        # Configure compiled regex match signatures for standard PII structures
        self.patterns = {
            "EMAIL": re.compile(r"[\w\.-]+@[\w\.-]+\.\w+"),
            "PHONE": re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"),
            "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
            "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
            "API_KEY": re.compile(r"\b(?:sk|sk-proj|ak|key|token)[a-zA-Z0-9\-_]{20,80}\b", re.IGNORECASE)
        }
        logger.info("PII Redactor engine operational with core pattern filters.")

    def redact(self, text: str) -> str:
        """
        Processes a block of text, replacing any matched PII entities with secure tokens.
        """
        if not text:
            return ""
            
        redacted_text = text
        for token, pattern in self.patterns.items():
            matches = pattern.findall(redacted_text)
            if matches:
                logger.warning(f"PII Redaction Alert: Matched {len(matches)} occurrences of type: {token}")
                # Replace with placeholder token
                redacted_text = pattern.sub(f"[REDACTED_{token}]", redacted_text)
                
        return redacted_text
