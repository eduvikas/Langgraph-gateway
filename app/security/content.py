import re
import unicodedata
from dataclasses import dataclass, field

def _sp(pattern: str) -> str:
    """Make every literal space outside a [...] class match any single whitespace character."""
    out, in_class, i = [], False, 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\" and i + 1 < len(pattern):
            out.append(pattern[i:i + 2]); i += 2; continue
        if c == "[": in_class = True
        elif c == "]": in_class = False
        out.append(r"\s" if (c == " " and not in_class) else c)
        i += 1
    return "".join(out)


def _context_rules(rules):
    """Expand (name, base_regex, ordinary_context) rules into (block_rules, flag_rules).

    A match BLOCKS unless it sits in an ordinary context (a document reference, the user's own
    earlier message, everyday scope...). In that context the same match is not discarded: it becomes
    a flag-only NAME_IN_CONTEXT finding, so an attempt that tries to hide inside a carve-out stays
    visible in the audit trail and is blocked when INJECTION_STRICT=true. `{CTX}` in a base marks
    where the context check goes; without it the check is appended at the end."""
    block, flagged = [], []
    for name, base, context in rules:
        if context is None:
            block.append((name, _sp(base))); continue
        neg, pos = "(?!" + context + ")", "(?=" + context + ")"
        if "{CTX}" in base:
            block.append((name, _sp(base.replace("{CTX}", neg)))); flagged.append((name + "_IN_CONTEXT", _sp(base.replace("{CTX}", pos))))
        else:
            block.append((name, _sp(base + neg))); flagged.append((name + "_IN_CONTEXT", _sp(base + pos)))
    return block, flagged


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
    # Prompt-injection rules, in two tiers.
    #
    # INJECTION_PATTERNS are high-confidence attack phrasings and BLOCK. They match the
    # attack itself (e.g. "ignore previous instructions"), not loose keyword pairs: the old
    # rules paired words like run/execute with command/tool, so ordinary developer requests
    # ("how do I execute a shell command?") were blocked as attacks.
    #
    # INJECTION_SUSPECT_PATTERNS look risky but are common in legitimate prompts. They are
    # recorded as PROMPT_INJECTION_SUSPECT findings (visible in the response and audit trail)
    # and only block when INJECTION_STRICT=true.
    #
    # Whitespace is normalised before matching (see assess), so newline- or space-padded
    # variants of a phrase match too. Every quantifier is bounded.
    #
    # A regex is a speed bump, not a defence. Real protection is layered: least-privilege
    # tools, output filtering, and a model-based classifier on top of rules like these.
    _ANCHOR = (r"(?:^|[.!?;:\n] ?|\b(?:and|then|now|please|instead) |"
               r"\b(?:want|need|asking|ask|tell|telling) you to |\byou (?:must|should|will|have to|need to) )")
    _SAFETY = r"(?:safety|content|security|ethical|moderation)"
    _UNRESTRICTED_ALTS = (r"unrestricted|unfiltered|jailbroken|uncensored|"
                          r"without (?:any )?(?:restrictions|filters|limits|rules|ethical guidelines)|"
                          r"no (?:restrictions|filters|limits|rules|ethical guidelines)")
    _UNRESTRICTED = "(?:" + _UNRESTRICTED_ALTS + ")"

    # What makes a match "ordinary context" (each is the text that FOLLOWS the matched phrase):
    _REFERS_TO_A_DOCUMENT = r" (?:in|on|of|from|at|within|inside|per|according to|regarding|concerning|about|for|under|by) "  # "...instructions in section 3"
    _USERS_OWN_MESSAGE = (r" (?:(?:i|we|he|she|they) (?:gave|sent|wrote|posted|told|shared|mentioned)|"
                          r"(?:that|which) (?:was|were) (?:sent|written|posted|shared|given))\b")
    # "no limits on spending" is scope; "no limits on what you can say" is a jailbreak.
    _EVERYDAY_SCOPE = (r" (?:on|about) (?!(?:what|your|you|content|topics?|outputs?|responses?|answers?|replies|language|"
                       r"anything|everything|how|the (?:content|topics?|outputs?|answers?|responses?))\b)\w")
    # "credentials request form", "password rotation guide": a compound noun is a document about secrets.
    _COMPOUND_NOUN = (r" (?!(?:to|from|and|or|in|on|via|at|into|of|for|stored|used|that|which|you|i|we|they|it|here|"
                      r"there|now|please|by|with|as|file|files|dump|export|contents|database|vault|store)\b)\w+")
    # "print the system prompt we drafted / for the bot / format": writing prompts, not stealing one.
    _ABOUT_WRITING_PROMPTS = (r" (?:we|i) | for (?:the|our|a|my|this) | (?:format|template|example|syntax|structure|schema|"
                              r"guidelines?|guide|best practices|checklist|design|documentation|outline|ideas|requirements)\b")

    INJECTION_PATTERNS, _CONTEXT_FLAGS = _context_rules([
        ("IGNORE_PRIOR_INSTRUCTIONS", r"(?i)\b(?:ignore|disregard|forget) (?:all |any |every )?(?:of )?(?:the |your |these |those )?(?:previous|prior|above|earlier|preceding) (?:instructions?|prompts?|rules|directions?|guidelines|commands)\b",
         _REFERS_TO_A_DOCUMENT + "|" + _USERS_OWN_MESSAGE + r"| about "),
        ("IGNORE_INSTRUCTIONS_GIVEN", r"(?i)\b(?:ignore|disregard|forget) (?:all |any |every )?(?:of )?(?:the |your |these |those )?(?:instructions?|rules|prompts?|directions?|guidelines) (?:above|before this|given to you|you (?:were|have been|had been) (?:given|told))\b", None),
        ("FORGET_EVERYTHING", r"(?i)\b(?:forget|ignore|disregard) (?:everything|all) (?:above|before|(?:that )?you (?:were|have been) (?:told|taught|instructed))\b", None),
        ("IGNORE_SYSTEM_PROMPT", r"(?im)" + _ANCHOR + r"(?:ignore|disregard|override|bypass|forget) (?:all )?(?:of )?(?:the |your )?(?:system|developer) (?:prompt|message|instructions?|rules)\b",
         _REFERS_TO_A_DOCUMENT + "|" + _USERS_OWN_MESSAGE),
        ("IGNORE_YOUR_RULES", r"(?i)\b(?:ignore|disregard|override|bypass|forget) (?:all )?(?:of )?your (?:system |developer )?(?:prompt|instructions?|rules|programming|guidelines|training)\b", None),
        ("PERSONA_JAILBREAK", r"(?i)\byou are now\b[^.\n]{0,40}\b(?:(?-i:DAN)|unrestricted|unfiltered|jailbroken|uncensored|in (?:jailbreak|developer|god) mode|no longer bound by|free from (?:all |any )?(?:restrictions|rules|limits|constraints)|(?:with|having) no (?:rules|restrictions|limits)|without (?:any )?(?:rules|restrictions|limits))\b", None),
        ("DAN_JAILBREAK", r"(?i)\b(?:you are|you're|respond as|answer as|act as|be|become|play) (?-i:DAN)\b|\bdo anything now\b", None),
        ("FROM_NOW_ON_UNRESTRICTED", r"(?i)\bfrom now on\b[^.\n]{0,80}\b(?:developer mode|jailbreak(?:en|ed)?|" + _UNRESTRICTED_ALTS + r")\b", _EVERYDAY_SCOPE),
        ("SAFETY_BYPASS", r"(?i)\b(?:bypass|disable|turn off|ignore|circumvent|remove) (?:all )?(?:of )?your " + _SAFETY + r" (?:filters?|guidelines|policies|restrictions|rules|guardrails|checks)\b", None),
        ("UNRESTRICTED_PERSONA", r"(?i)\b(?:act as|pretend (?:to be|(?:that )?you (?:are|have))|behave (?:as|like)|roleplay as|start over as|respond as|answer as|reply as|continue as)\b[^.\n]{0,40}\b" + _UNRESTRICTED + r"\b", _EVERYDAY_SCOPE),
        ("SYSTEM_PROMPT_EXFIL", r"(?im)" + _ANCHOR + r"(?:reveal|show(?: me)?|print|repeat|output|leak|dump|display|tell me) (?:me )?(?:all )?(?:of )?(?:the |your )?(?:system|developer|hidden|initial|original|secret) (?:prompt|instructions?|message)\b",
         _ABOUT_WRITING_PROMPTS),
        ("REPEAT_ABOVE_EXFIL", r"(?i)\brepeat\b[^.\n]{0,40}\b(?:words|text|everything|instructions|prompt) (?:above|before this)\b[^\n]{0,80}\bstarting with\b", None),
        ("SECRET_EXFIL", r"(?im)" + _ANCHOR + r"(?:send|post|upload|forward|email|exfiltrate|transmit)\b[^.\n]{0,80}(?:\b(?:api[ _-]?keys?|credentials|passwords?|secrets?|private keys?|access tokens?)\b|\.env\b){CTX}[^\n]{0,80}(?:https?://|\bto \S+@\S+)",
         _COMPOUND_NOUN),
    ])
    INJECTION_SUSPECT_PATTERNS = [(n, _sp(p)) for n, p in [
        ("DESTRUCTIVE_COMMAND", r"(?i)\brm -[a-z]*r[a-z]* (?:-[a-z]+ )*/|\bdrop (?:table|database)\b|\b(?:curl|wget)\b[^|\n]{0,200}\| ?(?:ba|z)?sh\b|\bchmod (?:-R )?777\b|\bmkfs(?:\.\w+)?\b"),
        ("PRIVILEGE_ROLE_CLAIM", r"(?i)\b(?:you are now|act as|pretend to be)\b[^.\n]{0,40}\b(?:system|administrator|admin|root)\b"),
        ("OVERRIDE_SYSTEM_PROMPT", r"(?i)\b(?:ignore|disregard|override|bypass)\b[^.\n]{0,40}\b(?:system|developer) (?:prompt|message|instructions?)\b"),
        ("ASKS_FOR_OWN_PROMPT", r"(?i)\b(?:what(?:'s| is| are)|tell me|show me|give me|share|print|reveal|output|repeat) (?:me )?(?:all )?(?:of )?your (?:system |initial |original |hidden |secret |developer )?(?:prompt|instructions?|rules)\b"),
        ("SYSTEM_PROMPT_MENTION", r"(?i)\b(?:reveal|show|print|leak|dump)\b[^.\n]{0,60}\b(?:system prompt|developer message|hidden instructions)\b"),
    ]] + _CONTEXT_FLAGS

    def __init__(self, strict_injection: bool = False):
        self.strict_injection = strict_injection

    @staticmethod
    def _normalise(text: str) -> str:
        """Fold look-alike and invisible characters, then collapse whitespace runs (keeping line
        breaks as sentence boundaries), so padded, line-split or zero-width-obfuscated phrases
        still match and long whitespace runs cannot slow the matcher. Finding offsets for
        injection rules therefore refer to this normalised text, not the original prompt."""
        text = unicodedata.normalize("NFKC", text)                      # full-width letters etc. -> ASCII
        text = re.sub("[\u200b\u200c\u200d\u2060\ufeff\u00ad]", "", text)   # zero-width / soft hyphen
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        return re.sub(r" ?\n[ \n]*", "\n", text)

    def assess(self, text: str, classification_hint: str = "auto") -> SecurityAssessment:
        findings: list[SecurityFinding] = []
        for category, pattern in self.PII_PATTERNS:
            for m in re.finditer(pattern, text): findings.append(SecurityFinding("PII", category, "high", m.start(), m.end()))
        for category, pattern in self.SECRET_PATTERNS:
            for m in re.finditer(pattern, text): findings.append(SecurityFinding("SECRET", category, "critical", m.start(), m.end()))
        normalised = self._normalise(text)
        for category, pattern in self.INJECTION_PATTERNS:
            for m in re.finditer(pattern, normalised): findings.append(SecurityFinding("PROMPT_INJECTION", category, "high", m.start(), m.end()))
        for category, pattern in self.INJECTION_SUSPECT_PATTERNS:
            for m in re.finditer(pattern, normalised): findings.append(SecurityFinding("PROMPT_INJECTION_SUSPECT", category, "medium", m.start(), m.end()))
        if any(f.category == "SECRET" for f in findings): classification = "restricted"
        elif any(f.category == "PII" for f in findings): classification = "confidential"
        else: classification = classification_hint if classification_hint in {"public", "internal", "confidential", "restricted"} else "internal"
        injection = any(f.category == "PROMPT_INJECTION" for f in findings) or (
            self.strict_injection and any(f.category == "PROMPT_INJECTION_SUSPECT" for f in findings))
        blocked = any(f.category == "SECRET" for f in findings) or injection
        reason = "SECRET_DETECTED" if any(f.category == "SECRET" for f in findings) else ("PROMPT_INJECTION_DETECTED" if injection else None)
        return SecurityAssessment(classification, findings, blocked, reason)
