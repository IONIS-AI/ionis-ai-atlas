"""Response models: the published /api/v1 contract. Field names follow the database, which follows
ADIF (ionis-core docs/IONIS-DATA-SPEC.md). Add fields freely; never rename or remove one."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Health(BaseModel):
    status: str


class Release(BaseModel):
    adif_version: str
    status: str
    released: Optional[datetime]
    source_url: str
    source_sha256: str


class Current(BaseModel):
    adif_version: str
    set_at: datetime


class Band(BaseModel):
    band: str
    lower_freq_mhz: Optional[float]
    upper_freq_mhz: Optional[float]
    import_only: bool


class Mode(BaseModel):
    mode: str
    description: Optional[str]
    import_only: bool
    submodes: list[str]


class DxccEntity(BaseModel):
    entity_code: int
    entity_name: str
    deleted: bool


class Contest(BaseModel):
    contest_id: str
    description: Optional[str]
    import_only: bool


class Field(BaseModel):
    field_name: str
    data_type: str
    enumeration: Optional[str]
    description: Optional[str]
    import_only: bool
