import pytest
from app.config import Settings

def test_production_rejects_auth_disabled():
    settings = Settings(app_env="production", auth_enabled=False, allow_insecure_local_auth=False)
    with pytest.raises(ValueError, match="AUTH_ENABLED must be true"):
        settings.validate_security_configuration()

def test_production_rejects_local_auth_bypass():
    settings = Settings(app_env="production", auth_enabled=True, allow_insecure_local_auth=True, jwt_secret="x" * 40)
    with pytest.raises(ValueError, match="ALLOW_INSECURE_LOCAL_AUTH must be false"):
        settings.validate_security_configuration()

def test_production_rejects_default_or_short_hmac_secret():
    default_secret = Settings(app_env="prod", auth_enabled=True, allow_insecure_local_auth=False, jwt_secret="change-me-in-production")
    with pytest.raises(ValueError, match="JWT_SECRET must be changed"):
        default_secret.validate_security_configuration()
    short_secret = Settings(app_env="prod", auth_enabled=True, allow_insecure_local_auth=False, jwt_secret="short-secret")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        short_secret.validate_security_configuration()

def test_production_accepts_explicitly_hardened_settings():
    settings = Settings(app_env="production", auth_enabled=True, allow_insecure_local_auth=False, jwt_secret="s" * 48)
    settings.validate_security_configuration()

def test_local_development_defaults_remain_usable():
    Settings(app_env="local", auth_enabled=False).validate_security_configuration()
