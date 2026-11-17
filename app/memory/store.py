from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Protocol
from sqlalchemy import create_engine, String, Integer, Text, ForeignKey, select, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session as DBSession

@dataclass
class SessionRecord:
    session_id: str
    user_id: str = ""
    application_id: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    request_count: int = 0

class SessionStore(Protocol):
    def get_or_create(self, session_id: str, user_id: str = "", application_id: str = "") -> SessionRecord: ...
    def append(self, session_id: str, role: str, content: str, user_id: str = "", application_id: str = "") -> None: ...
    def increment_request_count(self, session_id: str, user_id: str = "", application_id: str = "") -> int: ...
    def get_history(self, session_id: str, user_id: str = "") -> list[dict[str, Any]]: ...
    def delete(self, session_id: str, user_id: str = "") -> bool: ...

class InMemorySessionStore:
    def __init__(self):
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = RLock()

    def get_or_create(self, session_id, user_id="", application_id=""):
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionRecord(session_id, user_id, application_id)
            return self._sessions[session_id]

    def append(self, session_id, role, content, user_id="", application_id=""):
        with self._lock:
            session = self.get_or_create(session_id, user_id, application_id)
            session.messages.append({"role": role, "content": content})

    def increment_request_count(self, session_id, user_id="", application_id=""):
        with self._lock:
            session = self.get_or_create(session_id, user_id, application_id)
            session.request_count += 1
            return session.request_count

    def get_history(self, session_id, user_id=""):
        with self._lock:
            session = self.get_or_create(session_id, user_id)
            if user_id and session.user_id and session.user_id != user_id:
                raise PermissionError("SESSION_OWNER_MISMATCH")
            return list(session.messages)

    def delete(self, session_id, user_id=""):
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            if user_id and session.user_id and session.user_id != user_id:
                raise PermissionError("SESSION_OWNER_MISMATCH")
            return self._sessions.pop(session_id, None) is not None

class Base(DeclarativeBase): pass
class SessionRow(Base):
    __tablename__ = "gateway_sessions"
    session_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    application_id: Mapped[str] = mapped_column(String(100), index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
class MessageRow(Base):
    __tablename__ = "gateway_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("gateway_sessions.session_id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)

class SqlSessionStore:
    """Durable session memory. Works with SQLite locally and PostgreSQL in production."""
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True)
        Base.metadata.create_all(self.engine)

    def _owner(self, db, session_id, user_id, application_id=""):
        row = db.get(SessionRow, session_id)
        if row is None:
            row = SessionRow(session_id=session_id, user_id=user_id, application_id=application_id, request_count=0)
            db.add(row); db.flush()
        elif user_id and row.user_id != user_id:
            raise PermissionError("SESSION_OWNER_MISMATCH")
        return row

    def get_or_create(self, session_id, user_id="", application_id=""):
        with DBSession(self.engine) as db:
            row = self._owner(db, session_id, user_id, application_id)
            return SessionRecord(session_id, row.user_id, row.application_id, request_count=row.request_count)

    def append(self, session_id, role, content, user_id="", application_id=""):
        with DBSession(self.engine) as db:
            self._owner(db, session_id, user_id, application_id)
            db.add(MessageRow(session_id=session_id, role=role, content=content)); db.commit()

    def increment_request_count(self, session_id, user_id="", application_id=""):
        with DBSession(self.engine) as db:
            row = self._owner(db, session_id, user_id, application_id)
            row.request_count += 1; db.commit(); return row.request_count

    def get_history(self, session_id, user_id=""):
        with DBSession(self.engine) as db:
            self._owner(db, session_id, user_id)
            rows = db.scalars(select(MessageRow).where(MessageRow.session_id == session_id).order_by(MessageRow.id)).all()
            return [{"role": r.role, "content": r.content} for r in rows]

    def delete(self, session_id, user_id=""):
        with DBSession(self.engine) as db:
            row = db.get(SessionRow, session_id)
            if row is None: return False
            if user_id and row.user_id != user_id: raise PermissionError("SESSION_OWNER_MISMATCH")
            db.execute(delete(MessageRow).where(MessageRow.session_id == session_id))
            db.delete(row); db.commit(); return True

def build_session_store(settings):
    if settings.memory_backend.lower() == "memory":
        return InMemorySessionStore()
    return SqlSessionStore(settings.database_url)

session_store = build_session_store(__import__("app.config", fromlist=["get_settings"]).get_settings())
