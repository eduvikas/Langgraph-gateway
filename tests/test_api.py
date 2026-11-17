from fastapi.testclient import TestClient
from app.main import app
def test_health(): assert TestClient(app).get("/health").status_code==200
def test_config_hides_key(monkeypatch):
    # The response may name the flag (openai_api_key_configured) but must never carry the key itself.
    import app.api.routes_config as routes_config
    from app.config import Settings
    monkeypatch.setattr(routes_config, "get_settings", lambda: Settings(openai_api_key="sk-secret-value-123"))
    r=TestClient(app).get("/v1/config")
    assert "sk-secret-value-123" not in r.text
    assert r.json()["openai_api_key_configured"] is True
