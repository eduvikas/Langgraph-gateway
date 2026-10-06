from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Integer, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session as DBSession

class UsageBase(DeclarativeBase): pass
class UsageEvent(UsageBase):
    __tablename__ = "gateway_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    application_id: Mapped[str] = mapped_column(String(100), index=True)
    session_id: Mapped[str] = mapped_column(String(200), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    decision: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class UsageLedger:
    def __init__(self, database_url):
        self.engine = create_engine(database_url, future=True)
        UsageBase.metadata.create_all(self.engine)
    def record(self, **data):
        with DBSession(self.engine) as db:
            db.add(UsageEvent(**data)); db.commit()
    def recent(self, limit=20):
        with DBSession(self.engine) as db:
            rows = db.query(UsageEvent).order_by(UsageEvent.id.desc()).limit(limit).all()
            return [self._dict(r) for r in rows]
    @staticmethod
    def _dict(r):
        return {"request_id": r.request_id, "user_id": r.user_id, "application_id": r.application_id, "session_id": r.session_id, "provider": r.provider, "model": r.model, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "total_tokens": r.total_tokens, "decision": r.decision, "status": r.status, "created_at": r.created_at.isoformat()}

ledger = None
def build_ledger(settings):
    global ledger
    ledger = UsageLedger(settings.database_url)
    return ledger
