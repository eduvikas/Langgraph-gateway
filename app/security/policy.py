ORDER = {"public":0,"internal":1,"confidential":2,"restricted":3}
def classification_allowed(actual: str, maximum: str) -> bool: return ORDER.get(actual,3) <= ORDER.get(maximum,2)
