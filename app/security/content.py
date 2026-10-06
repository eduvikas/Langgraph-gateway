import re
from dataclasses import dataclass, field

@dataclass
class SecurityFinding:
    category: str
    pattern: str
    severity: str
    start: int = 0
    end: int = 0

@dataclass
class SecurityAssessment:
    classification: str
    findings: list[SecurityFinding] = field(default_factory=list)
    blocked: bool = False
    reason: str | None = None

class ContentSecurityEngine:
    """Deterministic baseline controls. Replace/augment with enterprise DLP/secret scanners later."""
    PII_PATTERNS = [
        ("EMAIL", r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        ("PHONE", r"\b(?:\+?\d[\d .-]{8,}\d)\b"),
        ("PAN_INDIA", r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
        ("AADHAAR_INDIA", r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
        ("CREDIT_CARD", r"\b(?:\d[ -]?){13,19}\b"),
    ]
    SECRET_PATTERNS = [
        ("OPENAI_KEY", r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        ("AWS_ACCESS_KEY", r"\bAKIA[0-9A-Z]{16}\b"),
        ("BEARER_TOKEN", r"\bBearer\s+[A-Za-z0-9._-]{20,}\b"),
        ("PRIVATE_KEY", r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        ("PASSWORD_ASSIGNMENT", r"(?i)\b(?:password|passwd|secret)\s*[:=]\s*\S+"),
    ]
    INJECTION_PATTERNS = [
        ("IGNORE_INSTRUCTIONS", r"(?i)\b(ignore|disregard|override)\b.{0,80}\b(previous|system|developer|instructions?)\b"),
        ("SYSTEM_PROMPT_EXFIL", r"(?i)\b(reveal|show|print|leak|dump)\b.{0,60}\b(system prompt|developer message|hidden instructions)\b"),
        ("ROLE_HIJACK", r"(?i)\b(you are now|act as|pretend to be)\b.{0,80}\b(admin|system|developer)\b"),
        ("TOOL_ABUSE", r"(?i)\b(run|execute|call)\b.{0,80}\b(shell|command|terminal|tool)\b"),
    ]

    def assess(self, text: str, classification_hint: str = "auto") -> SecurityAssessment:
        findings: list[SecurityFinding] = []
        for category, pattern in self.PII_PATTERNS:
            for m in re.finditer(pattern, text): findings.append(SecurityFinding("PII", category, "high", m.start(), m.end()))
        for category, pattern in self.SECRET_PATTERNS:
            for m in re.finditer(pattern, text): findings.append(SecurityFinding("SECRET", category, "critical", m.start(), m.end()))
        for category, pattern in self.INJECTION_PATTERNS:
            for m in re.finditer(pattern, text): findings.append(SecurityFinding("PROMPT_INJECTION", category, "high", m.start(), m.end()))
        if any(f.category == "SECRET" for f in findings): classification = "restricted"
        elif any(f.category == "PII" for f in findings): classification = "confidential"
        else: classification = classification_hint if classification_hint in {"public", "internal", "confidential", "restricted"} else "internal"
        blocked = any(f.category == "SECRET" for f in findings) or any(f.category == "PROMPT_INJECTION" for f in findings)
        reason = "SECRET_DETECTED" if any(f.category == "SECRET" for f in findings) else ("PROMPT_INJECTION_DETECTED" if any(f.category == "PROMPT_INJECTION" for f in findings) else None)
        return SecurityAssessment(classification, findings, blocked, reason)
