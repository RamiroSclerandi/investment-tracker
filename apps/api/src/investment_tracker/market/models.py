import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Enum, Numeric, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from investment_tracker.auth.models import Currency
from investment_tracker.core.models import Base, TimestampMixin


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
