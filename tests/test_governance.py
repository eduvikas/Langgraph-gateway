from app.config import Settings
from app.governance.engine import GovernanceEngine
from app.policy.store import PolicyStore
def test_governance_block():
    s=Settings(allowed_applications_raw="demo-app", allowed_models_raw="gpt-5.6-sol"); g=GovernanceEngine(s,PolicyStore("missing.json",s)); assert g.evaluate("bad","gpt-5.6-sol","hi",1).reason=="APPLICATION_NOT_ALLOWED"
def test_governance_allow():
    s=Settings(allowed_applications_raw="demo-app", allowed_models_raw="gpt-5.6-sol"); g=GovernanceEngine(s,PolicyStore("missing.json",s)); assert g.evaluate("demo-app","gpt-5.6-sol","hi",1).allowed
