"""Response models: the published /api/v1 contract. Field names follow the database, which follows
ADIF (ionis-core docs/IONIS-DATA-SPEC.md). Add fields freely; never rename or remove one."""

from datetime import datetime
from typing import Optional

from typing import Any

from pydantic import BaseModel


class Health(BaseModel):
    status: str


class Version(BaseModel):
    """The release this service runs: version e.g. "0.1.2" and the git revision it was built from.
    "dev" / "unknown" for anything not built by the publish script."""
    version: str
    revision: str


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


class DataType(BaseModel):
    data_type_name: str
    data_type_indicator: Optional[str]
    description: Optional[str]
    minimum_value: Optional[str]
    maximum_value: Optional[str]
    import_only: bool


class EnumerationSummary(BaseModel):
    name: str
    table: str
    records: int
    import_only_records: int


class Column(BaseModel):
    name: str
    type: str


class Enumeration(BaseModel):
    name: str
    adif_version: str
    columns: list[Column]
    rows: list[dict[str, Any]]
