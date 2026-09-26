"""IONIS Atlas API — read-only, versioned under /api/v1, documented at /api/docs.

The browser never talks to the database: this service holds the only connection, as a role that
can only SELECT (atlas_ro). Every query lives in this file, is parameterised, and is bounded.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .models import Band, Contest, Current, DxccEntity, Field, Health, Mode, Release

API = "/api/v1"
STATIC = Path(os.environ.get("ATLAS_STATIC", "/app/static"))  # React build + Swagger UI assets
DB_URL = os.environ.get("ATLAS_DB_URL", "postgresql://atlas_ro:atlas@db:5432/ionis")

pool: Optional[ConnectionPool] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    pool = ConnectionPool(DB_URL, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True)
    yield
    pool.close()


app = FastAPI(
    title="IONIS Atlas API",
    version="1.0.0",
    description=(
        "Read-only access to the published IONIS collection. Every field is defined by "
        "ADIF 3.1.7 or by the IONIS-AI extension (ionis-core docs/IONIS-DATA-SPEC.md). "
        "This description is a published contract: /api/v1 changes are additive only."
    ),
    lifespan=lifespan,
    docs_url=None,  # Swagger UI is served below from assets inside the image, not a CDN
    redoc_url=None,  # one place to look
    openapi_url=f"{API}/openapi.json",
)


def rows(sql: str, params: tuple = ()) -> list[dict]:
    assert pool is not None
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def version_or_current(adif_version: Optional[str]) -> str:
    if adif_version is None:
        cur = rows("SELECT adif_version FROM adif.current")
        if not cur:
            raise HTTPException(503, "No current ADIF version is set in this database")
        return cur[0]["adif_version"]
    if not rows("SELECT 1 FROM adif.release WHERE adif_version = %s", (adif_version,)):
        raise HTTPException(404, f"ADIF {adif_version} is not loaded in this database")
    return adif_version


VersionParam = Query(None, description="ADIF version, e.g. 3.1.7. Defaults to the lab's current version.")


@app.get(f"{API}/health", response_model=Health, tags=["service"])
def health() -> dict:
    rows("SELECT 1")
    return {"status": "ok"}


@app.get(f"{API}/adif/releases", response_model=list[Release], tags=["adif"])
def releases() -> list[dict]:
    """Every ADIF version loaded, with the SHA-256 of the adif.org file it was loaded from."""
    return rows(
        "SELECT adif_version, status, released, source_url, source_sha256 FROM adif.release ORDER BY adif_version"
    )


@app.get(f"{API}/adif/current", response_model=Current, tags=["adif"])
def current() -> dict:
    """The lab-wide current ADIF version."""
    got = rows("SELECT adif_version, set_at FROM adif.current")
    if not got:
        raise HTTPException(503, "No current ADIF version is set in this database")
    return got[0]


@app.get(f"{API}/adif/bands", response_model=list[Band], tags=["adif"])
def bands(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """ADIF's Band enumeration: name and frequency range in MHz, in frequency order."""
    v = version_or_current(adif_version)
    return rows(
        "SELECT band, lower_freq_mhz, upper_freq_mhz, coalesce(import_only, false) AS import_only "
        "FROM adif.band WHERE adif_version = %s ORDER BY lower_freq_mhz",
        (v,),
    )


@app.get(f"{API}/adif/modes", response_model=list[Mode], tags=["adif"])
def modes(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """ADIF's Mode enumeration, each with its submodes (e.g. MFSK → FT4)."""
    v = version_or_current(adif_version)
    return rows(
        "SELECT m.mode, m.description, coalesce(m.import_only, false) AS import_only, "
        "coalesce(array_agg(s.submode ORDER BY s.submode) FILTER (WHERE s.submode IS NOT NULL), '{}') AS submodes "
        "FROM adif.mode m LEFT JOIN adif.submode s ON s.adif_version = m.adif_version AND s.mode = m.mode "
        "WHERE m.adif_version = %s GROUP BY m.mode, m.description, m.import_only ORDER BY m.mode",
        (v,),
    )


@app.get(f"{API}/adif/dxcc", response_model=list[DxccEntity], tags=["adif"])
def dxcc(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """ADIF's DXCC Entity Code enumeration, deleted entities included and marked."""
    v = version_or_current(adif_version)
    return rows(
        "SELECT entity_code, entity_name, coalesce(deleted, false) AS deleted "
        "FROM adif.dxcc_entity_code WHERE adif_version = %s ORDER BY entity_code",
        (v,),
    )


@app.get(f"{API}/adif/contests", response_model=list[Contest], tags=["adif"])
def contests(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """ADIF's Contest_ID enumeration."""
    v = version_or_current(adif_version)
    return rows(
        "SELECT contest_id, description, coalesce(import_only, false) AS import_only "
        "FROM adif.contest_id WHERE adif_version = %s ORDER BY contest_id",
        (v,),
    )


@app.get(f"{API}/adif/fields", response_model=list[Field], tags=["adif"])
def fields(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """ADIF's fields: the vocabulary every IONIS column is defined against."""
    v = version_or_current(adif_version)
    return rows(
        "SELECT field_name, data_type, enumeration, description, "
        "coalesce(import_only, false) AS import_only FROM adif.field WHERE adif_version = %s ORDER BY field_name",
        (v,),
    )


# --- Swagger UI, self-hosted -------------------------------------------------------------------
@app.get("/api/docs", include_in_schema=False)
def swagger() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="IONIS Atlas API",
        swagger_js_url="/static/swagger/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger/swagger-ui.css",
        swagger_favicon_url="/static/swagger/favicon-32x32.png",
    )


# --- The React app (single-page: unknown paths serve index.html) -------------------------------
if (STATIC / "swagger").is_dir():
    app.mount("/static/swagger", StaticFiles(directory=STATIC / "swagger"), name="swagger")
if (STATIC / "web" / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "web" / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    index = STATIC / "web" / "index.html"
    if not index.is_file():
        raise HTTPException(404, "The web front end is not built into this image")
    return FileResponse(index)
