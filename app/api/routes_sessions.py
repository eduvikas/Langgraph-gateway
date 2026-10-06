from fastapi import APIRouter, HTTPException, Header
from app.memory.store import session_store
from app.security.identity import IdentityProvider, IdentityError
from app.config import get_settings
router=APIRouter(tags=["sessions"]); identity=IdentityProvider(get_settings())
def _user(user_id:str, authorization:str|None):
    try: return identity.authenticate(authorization,user_id,"")
    except IdentityError as exc: raise HTTPException(status_code=401,detail=str(exc))
@router.get("/sessions/{session_id}")
def get_session(session_id:str,user_id:str,authorization:str|None=Header(default=None)):
    ident=_user(user_id,authorization)
    try: return {"session_id":session_id,"user_id":ident.user_id,"messages":session_store.get_history(session_id,ident.user_id)}
    except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc))
@router.delete("/sessions/{session_id}")
def delete_session(session_id:str,user_id:str,authorization:str|None=Header(default=None)):
    ident=_user(user_id,authorization)
    try: return {"session_id":session_id,"deleted":session_store.delete(session_id,ident.user_id)}
    except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc))
