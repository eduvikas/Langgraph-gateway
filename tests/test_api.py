from fastapi.testclient import TestClient
from app.main import app
def test_health(): assert TestClient(app).get("/health").status_code==200
def test_config_hides_key():
    r=TestClient(app).get("/v1/config"); assert "openai_api_key" not in r.text
