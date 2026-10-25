"""Pydantic data models for the nedviga-cli JSON contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, computed_field


class ApiOutcomeEnvelope(BaseModel):
    """Strict single-JSON contract for every CLI command."""

    ok: bool
    status: Literal["ok", "degraded", "error"]
    reason: Optional[str] = None
    source: Optional[str] = None
    parsed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Optional[Any] = None
    metadata: dict = Field(default_factory=dict)


class PriceHistoryPoint(BaseModel):
    date: str
    price: float


class Pricing(BaseModel):
    price_total_rub: Optional[float] = None
    price_per_m2_rub: Optional[float] = None
    price_history: list[PriceHistoryPoint] = Field(default_factory=list)
    # v0.3.1 (реалтор-аудит §1): юридические условия сделки
    sale_type: Optional[str] = None          # free / alternative
    mortgage_allowed: Optional[bool] = None
    price_usd: Optional[float] = None
    price_eur: Optional[float] = None
    # v0.3.4 (ТЗ реалтора): торги/аукционы ДГИ/ЦУГИ
    is_auction: Optional[bool] = None
    trading_link: Optional[str] = None


class Parameters(BaseModel):
    rooms: Optional[int] = None
    rooms_type: Optional[str] = None
    area_total_m2: Optional[float] = None
    area_living_m2: Optional[float] = None
    area_kitchen_m2: Optional[float] = None
    floor: Optional[int] = None
    floors_total: Optional[int] = None
    ceiling_height_m: Optional[float] = None
    balcony: Optional[str] = None
    bathroom: Optional[str] = None
    renovation: Optional[str] = None
    window_view: Optional[str] = None
    # v0.3.1 (реалтор-аудит §3): физические параметры раздельно
    loggias_count: Optional[int] = None
    balconies_count: Optional[int] = None
    separate_wcs_count: Optional[int] = None
    combined_wcs_count: Optional[int] = None
    furniture: Optional[str] = None          # furnished / partially / no
    layouts: list[str] = Field(default_factory=list)  # URL схем БТИ
    # v0.4.0 (ТЗ реалтора): доля в квартире
    share_amount: Optional[float] = None


class Building(BaseModel):
    address_raw: Optional[str] = None
    # v0.4.3 (ТЗ the task brief, realtor): ЖК/комплекс из сниппета; только если явно помечен.
    complex: Optional[str] = None
    house_series: Optional[str] = None
    year_built: Optional[int] = None
    building_type: Optional[str] = None
    floor_material: Optional[str] = None
    renovation_program: Optional[bool] = None
    elevators_passenger: Optional[int] = None
    elevators_cargo: Optional[int] = None
    gas: Optional[bool] = None
    # v0.3.1 (реалтор-аудит §2, §4): здание + флаги
    has_garbage_chute: Optional[bool] = None
    parking_type: Optional[str] = None       # ground / underground
    is_apartments: Optional[bool] = None
    is_illegal_construction: Optional[bool] = None


class CianClaimedMetro(BaseModel):
    station: Optional[str] = None
    claimed_time_minutes: Optional[int] = None
    transport_type: Optional[str] = None


class HonestWalkRoute(BaseModel):
    target_station: Optional[str] = None
    target_vestibule: Optional[str] = None
    walk_distance_meters: Optional[int] = None
    walk_duration_minutes: Optional[float] = None
    routing_provider: Optional[str] = None
    route_verified: bool = False


class Geo(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    district: Optional[str] = None
    area_name: Optional[str] = None
    cian_claimed_metro: Optional[CianClaimedMetro] = None
    honest_walk_route: Optional[HonestWalkRoute] = None
    honest_overclaim: Optional[dict] = None  # v0.3.2: {'overclaim_minutes': N, 'flag': bool}


class Seller(BaseModel):
    seller_type: Optional[str] = None
    name: Optional[str] = None
    agent_phone_masked: Optional[str] = None
    # v0.3.1 (реалтор-аудит §4, §5)
    is_by_homeowner: Optional[bool] = None
    phones: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None          # дата публикации
    edit_date: Optional[str] = None           # дата последнего изменения


class Image(BaseModel):
    url: str
    category: Optional[str] = None


class ListingCard(BaseModel):
    """Full listing card schema used by import/get-card/search."""

    id: str
    source: str
    url: str
    status: Literal["active", "inactive", "sold", "removed"] = "active"
    title: Optional[str] = None

    pricing: Pricing = Field(default_factory=Pricing)
    parameters: Parameters = Field(default_factory=Parameters)
    building: Building = Field(default_factory=Building)
    geo: Geo = Field(default_factory=Geo)

    description_text: Optional[str] = None
    # v0.4.0 (ТЗ реалтора): категория объявления (flatShare и т.д.)
    category: Optional[str] = None
    seller: Seller = Field(default_factory=Seller)
    images: list[Image] = Field(default_factory=list)

    @computed_field
    @property
    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if self.pricing.price_total_rub is None:
            missing.append("price_total_rub")
        if self.parameters.area_total_m2 is None:
            missing.append("area_total_m2")
        if self.parameters.rooms is None:
            missing.append("rooms")
        if self.parameters.floor is None:
            missing.append("floor")
        if self.parameters.floors_total is None:
            missing.append("floors_total")
        if not (self.building.address_raw or "").strip():
            missing.append("address_raw")
        if not (self.geo.district or "").strip():
            missing.append("geo.district")
        return missing
