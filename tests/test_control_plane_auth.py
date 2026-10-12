"""With AUTH_ENABLED=true the control-plane endpoints must require an operator
(or admin) token. They used to answer anyone, leaking the audit log and per-user
usage while /v1/chat correctly demanded authentication."""
import jwt
import pytest
from fastapi.testclient import TestClient

import app.security.deps as deps
from app.config import Settings
from app.main import app

SECRET = "test-secret-with-enough-length-for-hs256"
PROTECTED = ["/v1/config", "/v1/security/audit", "/v1/usage/recent",
             "/v1/control-tower/overview", "/v1/evaluations/recent"]
client = TestClient(app)


def token(roles, sub="ops1"):
    return "Bearer " + jwt.encode({"sub": sub, "roles": roles}, SECRET, algorithm="HS256")


@pytest.fixture
def auth_on(monkeypatch):
    settings = Settings(auth_enabled=True, jwt_secret=SECRET, jwt_algorithm="HS256", jwt_issuer="", jwt_audience="")
    monkeypatch.setattr(deps, "get_settings", lambda: settings)


@pytest.mark.parametrize("path", PROTECTED)
def test_no_token_is_rejected(auth_on, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_viewer_is_forbidden(auth_on, path):
    r = client.get(path, headers={"Authorization": token(["viewer"])})
    assert r.status_code == 403 and r.json()["detail"] == "RBAC_DENIED:control_plane"


@pytest.mark.parametrize("path", PROTECTED)
@pytest.mark.parametrize("role", ["operator", "admin"])
def test_operator_and_admin_are_allowed(auth_on, path, role):
    assert client.get(path, headers={"Authorization": token([role])}).status_code == 200


def test_invalid_token_is_rejected(auth_on):
    assert client.get("/v1/usage/recent", headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401


def test_health_stays_public(auth_on):
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("path", PROTECTED)
def test_local_dev_mode_is_unchanged_when_auth_is_disabled(path):
    assert client.get(path).status_code == 200
