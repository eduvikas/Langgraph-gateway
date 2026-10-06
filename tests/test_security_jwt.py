import jwt
from app.config import Settings
from app.security.identity import IdentityProvider, IdentityError

def test_jwt_identity():
    s=Settings(auth_enabled=True,jwt_secret="test-secret",jwt_algorithm="HS256",jwt_issuer="",jwt_audience="")
    token=jwt.encode({"sub":"u1","roles":["operator"],"applications":["demo-app"]},s.jwt_secret,algorithm=s.jwt_algorithm)
    ident=IdentityProvider(s).authenticate("Bearer "+token,"u1","demo-app")
    assert ident.authenticated and "operator" in ident.roles

def test_jwt_user_mismatch():
    s=Settings(auth_enabled=True,jwt_secret="test-secret")
    token=jwt.encode({"sub":"u1"},s.jwt_secret,algorithm="HS256")
    try: IdentityProvider(s).authenticate("Bearer "+token,"u2","demo-app")
    except IdentityError as e: assert str(e)=="USER_ID_MISMATCH"
    else: assert False
