import jwt
from app.config import Settings
from app.security.identity import IdentityProvider, IdentityError

def test_jwt_identity():
    s=Settings(auth_enabled=True,jwt_secret="test-secret-with-at-least-32-bytes-long",jwt_algorithm="HS256",jwt_issuer="",jwt_audience="")
    token=jwt.encode({"sub":"u1","roles":["operator"],"applications":["demo-app"]},s.jwt_secret,algorithm=s.jwt_algorithm)
    ident=IdentityProvider(s).authenticate("Bearer "+token,"u1","demo-app")
    assert ident.authenticated and "operator" in ident.roles

def test_jwt_user_mismatch():
    s=Settings(auth_enabled=True,jwt_secret="test-secret-with-at-least-32-bytes-long")
    token=jwt.encode({"sub":"u1"},s.jwt_secret,algorithm="HS256")
    try: IdentityProvider(s).authenticate("Bearer "+token,"u2","demo-app")
    except IdentityError as e: assert str(e)=="USER_ID_MISMATCH"
    else: assert False


def test_application_scoped_token_must_include_application_claim():
    s=Settings(auth_enabled=True,jwt_secret="test-secret-with-enough-length-32bytes",jwt_algorithm="HS256")
    token=jwt.encode({"sub":"u1","roles":["developer"]},s.jwt_secret,algorithm=s.jwt_algorithm)
    try:
        IdentityProvider(s).authenticate("Bearer "+token,"u1","demo-app")
    except IdentityError as e:
        assert str(e)=="APPLICATION_CLAIM_REQUIRED"
    else:
        assert False, "application-scoped requests must require an application claim"
