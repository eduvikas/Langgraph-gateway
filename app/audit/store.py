from datetime import datetime, timezone
import json
from sqlalchemy import create_engine, String, Integer, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

class AuditBase(DeclarativeBase): pass
class AuditEvent(AuditBase):
    __tablename__ = "gateway_security_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    request_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    application_id: Mapped[str] = mapped_column(String(100), index=True)
    session_id: Mapped[str] = mapped_column(String(200), index=True)
    outcome: Mapped[str] = mapped_column(String(40))
    classification: Mapped[str] = mapped_column(String(30), default="internal")
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class AuditStore:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True)
        AuditBase.metadata.create_all(self.engine)
        # create_all does not add columns to an existing database. Apply a small,
        # backwards-compatible migration for deployments created before routing audit.
        from sqlalchemy import inspect, text
        columns = {column["name"] for column in inspect(self.engine).get_columns("gateway_security_audit")}
        if "routing_decision" not in columns:
            with self.engine.begin() as connection:
                connection.execute(text("ALTER TABLE gateway_security_audit ADD COLUMN routing_decision TEXT NULL"))
    def record(self, **data):
        routing_decision = data.get("routing_decision")
        if routing_decision is not None and not isinstance(routing_decision, str):
            data["routing_decision"] = json.dumps(routing_decision, sort_keys=True, separators=(",", ":"), default=str)
        with Session(self.engine) as db:
            db.add(AuditEvent(**data)); db.commit()
    def recent(self, limit=50):
        with Session(self.engine) as db:
            rows = db.query(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit).all()
            return [{"event_type": r.event_type, "request_id": r.request_id, "user_id": r.user_id, "application_id": r.application_id, "session_id": r.session_id, "outcome": r.outcome, "classification": r.classification, "details": r.details, "routing_decision": json.loads(r.routing_decision) if r.routing_decision else None, "created_at": r.created_at.isoformat()} for r in rows]

def build_audit_store(settings): return AuditStore(settings.database_url)
