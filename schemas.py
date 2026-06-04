from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Stage(str, Enum):
    CONFIRMED = "CONFIRMED"
    ITEM_COLLECTED = "ITEM_COLLECTED"  # 1.1 seller pickup
    DRY_CLEAN_IN = "DRY_CLEAN_IN"  # 1.2a hotel intake
    DRY_CLEAN_OUT = "DRY_CLEAN_OUT"  # 1.2b hotel release
    DELIVERED = "DELIVERED"  # 1.3 logistics drop-off


class Role(str, Enum):
    SELLER = "seller"
    HOTEL = "hotel"
    LOGISTICS = "logistics"
    RENTER = "renter"


class CreateOrderReq(BaseModel):
    item_code: str
    delivery_window: str = "2-4 hours"


class ScanReq(BaseModel):
    qr_token: dict
    role: Role
    notes: Optional[str] = None


class RevokeReq(BaseModel):
    reason: Optional[str] = "manual revocation"
