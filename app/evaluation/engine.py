from dataclasses import dataclass
from datetime import datetime, timezone
import re

@dataclass
class EvalResult:
    groundedness: float
    relevance: float
    safety: float
    concise: float
    overall: float
    passed: bool
    reasons: list[str]

class EvaluationEngine:
    def evaluate(self,prompt,response,security_findings=None):
        p=set(re.findall(r'\b\w+\b',prompt.lower())); r=set(re.findall(r'\b\w+\b',response.lower()))
        overlap=len(p&r)/max(1,len(p))
        concise=1.0 if len(response.split())<=180 else max(0.0,180/len(response.split()))
        safety=0.0 if any(f.get('severity')=='high' for f in (security_findings or [])) else 1.0
        relevance=min(1.0, overlap*2.0)
        groundedness=1.0 if response.strip() else 0.0
        overall=round((groundedness+relevance+safety+concise)/4,3)
        reasons=[]
        if relevance<0.35: reasons.append('LOW_RELEVANCE')
        if concise<0.7: reasons.append('TOO_VERBOSE')
        if safety<1: reasons.append('SECURITY_FINDING')
        return EvalResult(groundedness,relevance,safety,concise,overall,overall>=0.65,reasons)
