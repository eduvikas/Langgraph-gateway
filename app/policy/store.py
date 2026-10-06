import json
from pathlib import Path
from dataclasses import dataclass
@dataclass
class AppPolicy:
    enabled: bool = True
    allowed_models: set[str] | None = None
    max_requests_per_session: int | None = None
    max_prompt_chars: int | None = None
    required_roles: set[str] | None = None
    max_data_classification: str = "confidential"
    allow_pii: bool = True
    allow_secrets: bool = False
    allow_prompt_injection: bool = False
class PolicyStore:
    def __init__(self, path, settings): self.path=Path(path); self.settings=settings; self.policies=self._load()
    def _load(self):
        if not self.path.exists(): return {}
        raw=json.loads(self.path.read_text(encoding="utf-8"))
        return {k: AppPolicy(v.get("enabled",True), set(v.get("allowed_models",[])) or None, v.get("max_requests_per_session"), v.get("max_prompt_chars"), set(v.get("required_roles",[])) or None, v.get("max_data_classification","confidential"), v.get("allow_pii",True), v.get("allow_secrets",False), v.get("allow_prompt_injection",False)) for k,v in raw.get("applications",{}).items()}
    def get(self, application_id): return self.policies.get(application_id, AppPolicy())
