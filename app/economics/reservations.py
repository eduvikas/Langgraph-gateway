"""Cross-worker daily budget reservations backed by the shared SQL database.

Uses an atomic conditional UPDATE for reservation admission. SQLite is suitable for
single-host development; PostgreSQL is recommended for multi-worker production.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from sqlalchemy import String, Float, Integer, DateTime, create_engine, select, update, delete, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.exc import IntegrityError

class ReservationBase(DeclarativeBase):
    pass

class DailyBudgetRow(ReservationBase):
    __tablename__ = "gateway_daily_budget"
    application_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    day_utc: Mapped[str] = mapped_column(String(10), primary_key=True)
    spent_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reserved_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class BudgetReservationRow(ReservationBase):
    __tablename__ = "gateway_budget_reservations"
    request_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(100), index=True)
    day_utc: Mapped[str] = mapped_column(String(10))
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

class SQLBudgetReservations:
    def __init__(self, database_url: str, ledger, lease_seconds: int = 900):
        kwargs = {"future": True}
        if database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine = create_engine(database_url, **kwargs)
        ReservationBase.metadata.create_all(self.engine)
        # Safe additive migration for databases created by an earlier prototype build.
        cols = {c["name"] for c in inspect(self.engine).get_columns("gateway_budget_reservations")}
        if "expires_at" not in cols:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE gateway_budget_reservations ADD COLUMN expires_at TIMESTAMP"))
                conn.execute(text("UPDATE gateway_budget_reservations SET expires_at = created_at WHERE expires_at IS NULL"))
        self.ledger = ledger
        self.lease_seconds = max(120, int(lease_seconds))

    @staticmethod
    def today():
        return datetime.now(timezone.utc).date().isoformat()

    def _ensure_daily(self, db, app: str, day: str):
        row = db.get(DailyBudgetRow, (app, day))
        if row is not None:
            return row
        # Seed from the legacy usage ledger exactly once when a day's budget row is first created.
        seed = self.ledger.spend_today(app)
        dialect = self.engine.dialect.name
        if dialect == "sqlite":
            db.execute(text("INSERT INTO gateway_daily_budget (application_id, day_utc, spent_usd, reserved_usd, updated_at) VALUES (:a,:d,:s,0,:t) ON CONFLICT(application_id, day_utc) DO NOTHING"), {"a": app, "d": day, "s": seed, "t": datetime.now(timezone.utc)})
        elif dialect == "postgresql":
            db.execute(text("INSERT INTO gateway_daily_budget (application_id, day_utc, spent_usd, reserved_usd, updated_at) VALUES (:a,:d,:s,0,:t) ON CONFLICT (application_id, day_utc) DO NOTHING"), {"a": app, "d": day, "s": seed, "t": datetime.now(timezone.utc)})
        else:
            db.add(DailyBudgetRow(application_id=app, day_utc=day, spent_usd=seed, reserved_usd=0.0))
            db.flush()
        return db.get(DailyBudgetRow, (app, day))

    def status(self, app: str):
        day = self.today()
        with Session(self.engine) as db, db.begin():
            row = db.get(DailyBudgetRow, (app, day))
            if row is None:
                return {"spent_usd": self.ledger.spend_today(app), "reserved_usd": 0.0}
            self._reap_expired(db, app, day)
            return {"spent_usd": max(float(row.spent_usd), self.ledger.spend_today(app)), "reserved_usd": float(row.reserved_usd)}

    def _reap_expired(self, db, app: str, day: str):
        now = datetime.now(timezone.utc)
        active = db.scalars(select(BudgetReservationRow).where(BudgetReservationRow.application_id == app, BudgetReservationRow.day_utc == day, BudgetReservationRow.status == "active")).all()
        expired = [r for r in active if (r.expires_at.replace(tzinfo=timezone.utc) if r.expires_at.tzinfo is None else r.expires_at) < now]
        for reservation in expired:
            changed = db.execute(update(BudgetReservationRow).where(BudgetReservationRow.request_id == reservation.request_id, BudgetReservationRow.status == "active").values(status="expired")).rowcount
            if changed:
                row = db.get(DailyBudgetRow, (app, day))
                if row:
                    row.reserved_usd = max(0.0, float(row.reserved_usd) - float(reservation.amount_usd))
                    row.updated_at = now

    def reserve(self, app: str, request_id: str, amount: float, limit: float) -> bool:
        day = self.today(); amount = max(0.0, round(float(amount), 8))
        try:
            with Session(self.engine) as db, db.begin():
                self._ensure_daily(db, app, day)
                self._reap_expired(db, app, day)
                # Reconcile with the usage ledger exactly as status() does, so admission can never be
                # more permissive than the reported budget (e.g. spend recorded outside settle()).
                ledger_spend = float(self.ledger.spend_today(app))
                db.execute(update(DailyBudgetRow).where(
                    DailyBudgetRow.application_id == app, DailyBudgetRow.day_utc == day,
                    DailyBudgetRow.spent_usd < ledger_spend).values(spent_usd=ledger_spend))
                # Idempotency: the same request cannot reserve twice.
                if db.get(BudgetReservationRow, request_id) is not None:
                    return False
                stmt = update(DailyBudgetRow).where(
                    DailyBudgetRow.application_id == app, DailyBudgetRow.day_utc == day,
                    DailyBudgetRow.spent_usd + DailyBudgetRow.reserved_usd + amount <= float(limit) + 1e-12
                ).values(reserved_usd=DailyBudgetRow.reserved_usd + amount, updated_at=datetime.now(timezone.utc))
                changed = db.execute(stmt).rowcount
                if not changed:
                    return False
                db.add(BudgetReservationRow(request_id=request_id, application_id=app, day_utc=day, amount_usd=amount, status="active", expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)))
                db.flush()
                return True
        except IntegrityError:
            # A simultaneous retry with the same request ID loses the unique-key race;
            # its transaction (including the reserved amount update) is rolled back.
            return False

    def settle(self, request_id: str, actual_cost: float | None):
        with Session(self.engine) as db, db.begin():
            r = db.get(BudgetReservationRow, request_id)
            if r is None or r.status not in {"active", "expired"}:
                return False
            was_active = r.status == "active"
            row = db.get(DailyBudgetRow, (r.application_id, r.day_utc))
            if row:
                if was_active:
                    row.reserved_usd = max(0.0, float(row.reserved_usd) - float(r.amount_usd))
                if actual_cost is not None:
                    # Even if the lease expired while a provider call was running, reconcile
                    # the real charge. An overrun is surfaced rather than silently lost.
                    row.spent_usd = round(float(row.spent_usd) + max(0.0, float(actual_cost)), 8)
                row.updated_at = datetime.now(timezone.utc)
            r.status = "settled" if actual_cost is not None else "released"
            return True

    def release(self, request_id: str):
        return self.settle(request_id, None)
