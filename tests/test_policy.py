import json
from app.policy.store import PolicyStore
from app.config import Settings
def test_policy(tmp_path):
    p=tmp_path/"p.json"; p.write_text(json.dumps({"applications":{"x":{"enabled":False}}})); s=Settings(policy_file=str(p)); assert PolicyStore(str(p),s).get("x").enabled is False
