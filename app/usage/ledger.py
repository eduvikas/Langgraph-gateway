from datetime import datetime, timedelta, timezone
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, case, create_engine, func, inspect, text
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
    # Economics. cost_usd is what this call cost; baseline_cost_usd is the same tokens priced on the
    # baseline model; for cache hits, avoided_cost_usd is what the call would have cost on its own
    # model and tokens_avoided the tokens that were not spent (the consumed token columns are 0).
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    baseline_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    avoided_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    priced: Mapped[bool] = mapped_column(Boolean, default=True)
    tokens_avoided: Mapped[int] = mapped_column(Integer, default=0)


class UsageLedger:
    # Added after the first release; create_all() does not alter existing tables, so these are
    # added in place on start-up when a database from an older version is opened.
    ADDED_COLUMNS = {"cost_usd": "FLOAT DEFAULT 0", "baseline_cost_usd": "FLOAT DEFAULT 0",
                     "avoided_cost_usd": "FLOAT DEFAULT 0", "cache_hit": "BOOLEAN DEFAULT FALSE",
                     "priced": "BOOLEAN DEFAULT TRUE", "tokens_avoided": "INTEGER DEFAULT 0"}

    def __init__(self, database_url):
        self.engine = create_engine(database_url, future=True)
        UsageBase.metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self):
        existing = {c["name"] for c in inspect(self.engine).get_columns(UsageEvent.__tablename__)}
        with self.engine.begin() as conn:
            for name, ddl in self.ADDED_COLUMNS.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {UsageEvent.__tablename__} ADD COLUMN {name} {ddl}"))

    def record(self, **data):
        with DBSession(self.engine) as db:
            db.add(UsageEvent(**data)); db.commit()

    def recent(self, limit=20):
        with DBSession(self.engine) as db:
            rows = db.query(UsageEvent).order_by(UsageEvent.id.desc()).limit(limit).all()
            return [self._dict(r) for r in rows]

    # ---- aggregates (computed in SQL, so they are exact however many rows exist) ----
    @staticmethod
    def _columns():
        return (func.count(UsageEvent.id).label("requests"),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0.0).label("cost_usd"),
                func.coalesce(func.sum(UsageEvent.baseline_cost_usd), 0.0).label("baseline_cost_usd"),
                func.coalesce(func.sum(UsageEvent.avoided_cost_usd), 0.0).label("avoided_cost_usd"),
                func.coalesce(func.sum(UsageEvent.tokens_avoided), 0).label("tokens_avoided"),
                func.coalesce(func.sum(case((UsageEvent.cache_hit.is_(True), 1), else_=0)), 0).label("cache_hits"),
                func.coalesce(func.sum(case((UsageEvent.priced.is_(False), 1), else_=0)), 0).label("unpriced_requests"),
                func.coalesce(func.sum(case((UsageEvent.decision == "BLOCK", 1), else_=0)), 0).label("blocked"),
                func.coalesce(func.sum(case((UsageEvent.status == "success", 1), else_=0)), 0).label("successful"))

    @staticmethod
    def _clean(row, **extra):
        out = {k: (round(v, 8) if isinstance(v, float) else v) for k, v in row._asdict().items()}
        out.update(extra); return out

    def _query(self, db, *columns, since=None, application_id=None):
        q = db.query(*columns)
        if since is not None: q = q.filter(UsageEvent.created_at >= since)
        if application_id: q = q.filter(UsageEvent.application_id == application_id)
        return q

    def totals(self, since=None, application_id=None):
        with DBSession(self.engine) as db:
            return self._clean(self._query(db, *self._columns(), since=since, application_id=application_id).one())

    def by_application(self, since=None):
        with DBSession(self.engine) as db:
            rows = (self._query(db, UsageEvent.application_id, *self._columns(), since=since)
                    .group_by(UsageEvent.application_id).order_by(func.sum(UsageEvent.cost_usd).desc()).all())
            return [self._clean(r) for r in rows]

    def by_model(self, since=None):
        with DBSession(self.engine) as db:
            rows = (self._query(db, UsageEvent.provider, UsageEvent.model, *self._columns(), since=since)
                    .group_by(UsageEvent.provider, UsageEvent.model).order_by(func.sum(UsageEvent.cost_usd).desc()).all())
            return [self._clean(r) for r in rows]

    @staticmethod
    def utc_day_start(now=None):
        now = now or datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def spend_today(self, application_id, now=None):
        """USD spent by one application since 00:00 UTC today."""
        with DBSession(self.engine) as db:
            value = (self._query(db, func.coalesce(func.sum(UsageEvent.cost_usd), 0.0),
                                 since=self.utc_day_start(now), application_id=application_id).scalar())
            return round(float(value or 0.0), 8)

    @staticmethod
    def _dict(r):
        return {"request_id": r.request_id, "user_id": r.user_id, "application_id": r.application_id,
                "session_id": r.session_id, "provider": r.provider, "model": r.model,
                "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "total_tokens": r.total_tokens,
                "decision": r.decision, "status": r.status, "created_at": r.created_at.isoformat(),
                "cost_usd": r.cost_usd or 0.0, "baseline_cost_usd": r.baseline_cost_usd or 0.0,
                "avoided_cost_usd": r.avoided_cost_usd or 0.0, "cache_hit": bool(r.cache_hit),
                "priced": bool(r.priced), "tokens_avoided": r.tokens_avoided or 0}


ledger = None
def build_ledger(settings):
    global ledger
    ledger = UsageLedger(settings.database_url)
    return ledger
