from datetime import datetime, timezone
from threading import Lock
class EvaluationStore:
    def __init__(self): self._lock=Lock(); self.events=[]
    def record(self,**data):
        with self._lock: self.events.append({'created_at':datetime.now(timezone.utc).isoformat(),**data})
    def recent(self,limit=50):
        with self._lock: return list(reversed(self.events[-limit:]))
store=EvaluationStore()
