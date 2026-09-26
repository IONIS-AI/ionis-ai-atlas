"""IONIS-AI Atlas API — read-only, versioned under /api/v1, documented at /api/docs.

The browser never talks to the database: this service holds the only connection, as a role that
can only SELECT (atlas_ro). Every query lives in this file, is parameterised, and is bounded.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .models import (Band, Contest, Current, DataType, DxccEntity, Enumeration, EnumerationSummary, Field,
                     Health, Mode, Release)

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
    title="IONIS-AI Atlas API",
    version="1.0.0",
    description=(
        "Read-only access to the published IONIS-AI collection. Every field is defined by "
        "ADIF 3.1.7 or by the IONIS-AI extension (ionis-core docs/IONIS-DATA-SPEC.md). "
        "This description is a published contract: /api/v1 changes are additive only."
    ),
    lifespan=lifespan,
    docs_url=None,  # Swagger UI is served below from assets inside the image, not a CDN
    redoc_url=None,  # one place to look
    openapi_url=f"{API}/openapi.json",
)

# --- The browser boundary (Atlas SPEC.md, "Security") -------------------------------------------
# The threat to a local app is a hostile page in the user's own browser reaching localhost:8080.
# Answering only localhost names closes DNS rebinding: a page on evil.example that re-points its
# name at 127.0.0.1 still sends "Host: evil.example", and is refused. Serving any other name means
# serving a network, which needs HTTPS; that arrives with TLS, not before.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Everything is self-hosted, so the policy allows Atlas's own origin and nothing else. Inline
# styles stay allowed for the component libraries; inline and injected scripts do not.
CSP = "; ".join([
    "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:", "font-src 'self'", "connect-src 'self'", "object-src 'none'",
    "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


@app.middleware("http")  # added after the host check, so it wraps it: refusals carry the headers too
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


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
    """ADIF's fields: the vocabulary every IONIS-AI column is defined against."""
    v = version_or_current(adif_version)
    return rows(
        "SELECT field_name, data_type, enumeration, description, "
        "coalesce(import_only, false) AS import_only FROM adif.field WHERE adif_version = %s ORDER BY field_name",
        (v,),
    )


@app.get(f"{API}/adif/datatypes", response_model=list[DataType], tags=["adif"])
def datatypes(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """ADIF's data types (GridSquare, Date, Number, ...)."""
    v = version_or_current(adif_version)
    return rows(
        "SELECT data_type_name, data_type_indicator, description, minimum_value, maximum_value, "
        "coalesce(import_only, false) AS import_only FROM adif.datatype WHERE adif_version = %s ORDER BY data_type_name",
        (v,),
    )


# Tables in the adif schema that are not enumerations.
_NOT_ENUMS = ("release", "current", "datatype", "field")


def enumeration_tables() -> dict[str, str]:
    """ADIF enumeration name -> table, read from the database itself (never from a hand list), so a
    name from a request is only ever matched against tables that exist."""
    tables = [r["table_name"] for r in rows(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'adif' "
        "AND table_type = 'BASE TABLE' AND NOT (table_name = ANY(%s)) ORDER BY table_name", (list(_NOT_ENUMS),))]
    out = {}
    for t in tables:
        name = rows(sql.SQL("SELECT record->>'Enumeration Name' AS n FROM adif.{} LIMIT 1").format(sql.Identifier(t)))
        out[(name[0]["n"] if name and name[0]["n"] else t)] = t
    return out


@app.get(f"{API}/adif/enumerations", response_model=list[EnumerationSummary], tags=["adif"])
def enumerations(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """Every ADIF enumeration, with its record count for the version (25 for ADIF 3.1.x)."""
    v = version_or_current(adif_version)
    out = []
    for name, t in enumeration_tables().items():
        c = rows(sql.SQL("SELECT count(*) AS n, count(*) FILTER (WHERE import_only) AS io FROM adif.{} "
                         "WHERE adif_version = %s").format(sql.Identifier(t)), (v,))[0]
        out.append({"name": name, "table": t, "records": c["n"], "import_only_records": c["io"]})
    return sorted(out, key=lambda e: e["name"].lower())


@app.get(f"{API}/adif/enumerations/{{name}}", response_model=Enumeration, tags=["adif"])
def enumeration(name: str, adif_version: Optional[str] = VersionParam) -> dict:
    """One ADIF enumeration, every record, with the columns ADIF defines for it. `name` is ADIF's
    enumeration name (e.g. Propagation_Mode) or its table name; anything else is 404."""
    v = version_or_current(adif_version)
    tables = enumeration_tables()
    by_table = {t: n for n, t in tables.items()}
    table = tables.get(name) or (name if name in by_table else None)
    if table is None:
        raise HTTPException(404, f"No ADIF enumeration named {name!r}")
    cols = rows(
        "SELECT column_name AS name, data_type AS type FROM information_schema.columns "
        "WHERE table_schema = 'adif' AND table_name = %s AND column_name NOT IN ('adif_version', 'record') "
        "ORDER BY ordinal_position", (table,))
    data = rows(sql.SQL("SELECT {} FROM adif.{} WHERE adif_version = %s ORDER BY record_key").format(
        sql.SQL(", ").join(sql.Identifier(c["name"]) for c in cols), sql.Identifier(table)), (v,))
    return {"name": by_table[table], "adif_version": v, "columns": cols, "rows": data}


# --- Swagger UI, self-hosted -------------------------------------------------------------------
# FastAPI's own page initialises Swagger UI in an inline <script>, which the policy above refuses,
# so the page loads its initialiser as a file instead.
SWAGGER_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IONIS-AI Atlas API</title>
<link rel="stylesheet" href="/static/swagger/swagger-ui.css">
<link rel="icon" href="/static/swagger/favicon-32x32.png">
</head>
<body>
<div id="swagger-ui"></div>
<script src="/static/swagger/swagger-ui-bundle.js"></script>
<script src="/api/docs/init.js"></script>
</body>
</html>
"""
SWAGGER_INIT = f"""SwaggerUIBundle({{
  url: "{API}/openapi.json",
  dom_id: "#swagger-ui",
  layout: "BaseLayout",
  deepLinking: true,
  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
}});
"""


@app.get("/api/docs", include_in_schema=False)
def swagger() -> HTMLResponse:
    return HTMLResponse(SWAGGER_PAGE)


@app.get("/api/docs/init.js", include_in_schema=False)
def swagger_init() -> Response:
    return Response(SWAGGER_INIT, media_type="text/javascript")


# --- The React app (single-page: unknown paths serve index.html) -------------------------------
if (STATIC / "swagger").is_dir():
    app.mount("/static/swagger", StaticFiles(directory=STATIC / "swagger"), name="swagger")
if (STATIC / "web" / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "web" / "assets"), name="assets")


# HEAD as well as GET: a reverse proxy or uptime checker probing "/" should not get 405.
@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    index = STATIC / "web" / "index.html"
    if not index.is_file():
        raise HTTPException(404, "The web front end is not built into this image")
    return FileResponse(index)
