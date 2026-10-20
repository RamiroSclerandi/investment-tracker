import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from investment_tracker.auth.models import Currency
from investment_tracker.core.models import Base, TimestampMixin
from investment_tracker.market.providers.base import HolidayKind


class AssetType(enum.StrEnum):
    CRYPTO = "CRYPTO"
    STOCK_AR = "STOCK_AR"
    STOCK_US = "STOCK_US"
    CEDEAR = "CEDEAR"
    SOV_BONDS = "SOV_BONDS"
    FIXED_RATE_AR = "FIXED_RATE_AR"
    CORP_BONDS = "CORP_BONDS"
    MUTUAL_FUNDS = "MUTUAL_FUNDS"


def _enum_values(enum_type: type[enum.StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("provider", "provider_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, name="asset_type", values_callable=_enum_values)
    )
    symbol: Mapped[str]
    name: Mapped[str]
    quote_currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency", values_callable=_enum_values)
    )
    price_factor: Mapped[Decimal] = mapped_column(Numeric(30, 10), server_default=text("1"))
    maturity_date: Mapped[date | None]
    fci_category: Mapped[str | None]
    provider: Mapped[str]
    provider_ref: Mapped[str]
    live_provider: Mapped[str | None]
    is_tracked: Mapped[bool] = mapped_column(server_default=text("false"))


class JobRunStatus(enum.StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED_LOCKED = "SKIPPED_LOCKED"
    NOT_DUE = "NOT_DUE"


class FxRateType(enum.StrEnum):
    MEP = "MEP"


class LatestPrice(TimestampMixin, Base):
    __tablename__ = "latest_prices"

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.assets.id"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str]


class AssetPrice(TimestampMixin, Base):
    __tablename__ = "asset_prices"

    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.assets.id"), primary_key=True)
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    source: Mapped[str]


_FX_RATE_TYPE = Enum(FxRateType, name="fx_rate_type", values_callable=_enum_values)


class FxRate(TimestampMixin, Base):
    __tablename__ = "fx_rates"

    rate_type: Mapped[FxRateType] = mapped_column(_FX_RATE_TYPE, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    buy: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    sell: Mapped[Decimal] = mapped_column(Numeric(20, 6))


class FxLatest(TimestampMixin, Base):
    __tablename__ = "fx_latest"

    rate_type: Mapped[FxRateType] = mapped_column(_FX_RATE_TYPE, primary_key=True)
    buy: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    sell: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRun(TimestampMixin, Base):
    __tablename__ = "job_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[JobRunStatus] = mapped_column(
        Enum(JobRunStatus, name="job_run_status", values_callable=_enum_values)
    )
    items_ok: Mapped[int] = mapped_column(default=0)
    items_failed: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class MarketHoliday(TimestampMixin, Base):
    __tablename__ = "market_holidays"

    day: Mapped[date] = mapped_column("date", primary_key=True)
    kind: Mapped[HolidayKind] = mapped_column(
        Enum(HolidayKind, name="holiday_kind", values_callable=_enum_values)
    )
    name: Mapped[str]
