"""IONIS-AI Atlas API — read-only, versioned under /api/v1, documented at /api/docs.

The browser never talks to the database: this service holds the only connection, as a role that
can only SELECT (atlas_ro). Every query lives in this file, is parameterised, and is bounded.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .models import (Band, Contest, Current, DataType, DxccEntity, Enumeration, EnumerationSummary, Field,
                     Health, Mode, Release, Version)

API = "/api/v1"
# The release, built into the image by publish.sh (Containerfile ARG -> ENV). Image LABELS carry it
# too, but a container cannot read its own labels. Anything publish did not build says "dev", so an
# unreleased build can never report itself as a release.
VERSION = os.environ.get("ATLAS_VERSION") or "dev"
REVISION = os.environ.get("ATLAS_REVISION") or "unknown"
STATIC = Path(os.environ.get("ATLAS_STATIC", "/app/static"))  # React build + Swagger UI assets
DB_URL = os.environ.get("ATLAS_DB_URL", "postgresql://atlas_ro:atlas@db:5432/ionis")

pool: Optional[ConnectionPool] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global pool
    # check: test each connection before handing it out, so one killed by a database restart is
    # replaced rather than surfacing as a 500 on the next request.
    pool = ConnectionPool(DB_URL, min_size=1, max_size=8, kwargs={"row_factory": dict_row},
                          check=ConnectionPool.check_connection, open=True)
    yield
    pool.close()


app = FastAPI(
    title="IONIS-AI Atlas API",
    version=VERSION,
    description=(
        "Read-only access to the published IONIS-AI collection. Every field is defined by "
        "ADIF (the loaded versions are listed at /api/v1/adif/releases, the current one at "
        "/api/v1/adif/current) or by the IONIS-AI extension (ionis-core docs/IONIS-DATA-SPEC.md). "
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

# --- Lists: paged and filtered on the server (SPEC R15) -----------------------------------------
# Every list endpoint takes `limit`, `offset` and `q`, and filters, counts and pages in SQL, BEFORE
# the page is cut. A filter applied in the browser sees only the page it was given, so once pages
# exist, client-side filtering silently misses matches.
#
# ADDITIVE, as the contract requires: without `limit` an endpoint returns every row, exactly as it
# did before R15. Endpoints that return a bare JSON array cannot grow a `total` field without
# changing their shape, so the count travels in headers, the convention for paged arrays:
# `X-Total-Count` (rows matching the filters) and `Link: <...>; rel="next"` while more remain.
# Reference data pages by OFFSET: it is thousands of rows. Collection data will use a keyset
# cursor, because OFFSET reads every row it skips.
MAX_LIMIT = 1000
LimitParam = Query(None, ge=1, le=MAX_LIMIT,
                   description=f"Rows per page, 1 to {MAX_LIMIT}. Omit to get every row (the pre-R15 behaviour).")
OffsetParam = Query(0, ge=0, description="Rows to skip, for the page after `limit` rows.")
SearchParam = Query(None, min_length=1, max_length=100,
                    description="Case-insensitive text search across the listed columns, applied before paging.")
PAGED = {200: {"headers": {
    "X-Total-Count": {"description": "Rows matching the filters, across all pages", "schema": {"type": "integer"}},
    "Link": {"description": 'Present while more rows remain: `<url>; rel="next"`', "schema": {"type": "string"}},
}}}


def _contains(q: str) -> str:
    """`q` as a literal substring for ILIKE: its own % and _ must not act as wildcards."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def paged(request: Request, response: Response, base: str | sql.Composable, args: tuple, columns: list[str],
          order: list[str], limit: Optional[int], offset: int, q: Optional[str],
          where: Optional[dict[str, str]] = None) -> tuple[list[dict], int]:
    """Run `base` (a SELECT without ORDER BY) as a subquery; search `columns` for `q`, apply exact
    `where` filters, count, order by `order` (unique, so pages never overlap) and page. Column names
    here come from code or from information_schema, never from a request, and are quoted anyway."""
    base = sql.SQL(base) if isinstance(base, str) else base
    conds, params = [], list(args)
    if q:
        conds.append(sql.SQL("({})").format(sql.SQL(" OR ").join(
            sql.SQL("t.{}::text ILIKE %s ESCAPE '\\'").format(sql.Identifier(c)) for c in columns)))
        params += [_contains(q)] * len(columns)
    for col, val in (where or {}).items():
        conds.append(sql.SQL("t.{}::text = %s").format(sql.Identifier(col)))
        params.append(val)
    filt = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conds) if conds else sql.SQL("")
    total = rows(sql.SQL("SELECT count(*) AS n FROM ({}) t").format(base) + filt, tuple(params))[0]["n"]
    page = (sql.SQL("SELECT * FROM ({}) t").format(base) + filt + sql.SQL(" ORDER BY ")
            + sql.SQL(", ").join(sql.SQL("t.{}").format(sql.Identifier(o)) for o in order))
    if limit is not None:
        page += sql.SQL(" LIMIT %s OFFSET %s")
        params += [limit, offset]
    elif offset:
        page += sql.SQL(" OFFSET %s")
        params.append(offset)
    data = rows(page, tuple(params))
    response.headers["X-Total-Count"] = str(total)
    if limit is not None and offset + limit < total:
        nxt = request.url.include_query_params(limit=limit, offset=offset + limit)
        response.headers["Link"] = f'<{nxt.path}?{nxt.query}>; rel="next"'
    return data, total


@app.get(f"{API}/health", response_model=Health, tags=["service"])
def health() -> dict:
    rows("SELECT 1")
    return {"status": "ok"}


@app.get(f"{API}/version", response_model=Version, tags=["service"])
def version() -> dict:
    """Which release this service runs. What the image says about itself: proof that a deployment
    runs a signed release is verifying the running image's digest (see SIGNING.md)."""
    return {"version": VERSION, "revision": REVISION}


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


# --- Curated views degrade, never break (SPEC R17) ----------------------------------------------
# A curated view names ADIF columns. A later ADIF version that drops one must not turn the view into
# a 500: the column is looked up in the database (per request, since the engine can upgrade its schema
# while this service runs) and a dropped one selects a fallback the response model still accepts.
# The columns ADIF adds appear in the generic /adif/enumerations/<table> view without any change here.
def present(table: str) -> set[str]:
    return {r["column_name"] for r in rows(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'adif' AND table_name = %s", (table,))}


FLAG = "false"   # a flag ADIF leaves empty (import_only, deleted) reads false, present or not


def pick(table: str, cols: list[tuple[str, str]], alias: Optional[str] = None) -> sql.Composable:
    """A SELECT list: each (column, fallback SQL) as the column if the table has it, else the
    fallback, always named as the column. A FLAG column is coalesced to false either way, since
    ADIF leaves it empty on most rows and the response models require a boolean."""
    have = present(table)
    ref = (lambda c: sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(c))) if alias else sql.Identifier

    def expr(c: str, fallback: str) -> sql.Composable:
        if c not in have:
            return sql.SQL(fallback)
        return sql.SQL("coalesce({}, false)").format(ref(c)) if fallback == FLAG else ref(c)
    return sql.SQL(", ").join(sql.SQL("{} AS {}").format(expr(c, f), sql.Identifier(c)) for c, f in cols)


# The four routes below are curated views published before R16. They stay (the contract is
# additive), and each names its canonical route: /adif/enumerations/<table> (SPEC R16).
@app.get(f"{API}/adif/bands", response_model=list[Band], tags=["adif"], responses=PAGED)
def bands(request: Request, response: Response, adif_version: Optional[str] = VersionParam,
          limit: Optional[int] = LimitParam, offset: int = OffsetParam, q: Optional[str] = SearchParam) -> list[dict]:
    """ADIF's Band enumeration: name and frequency range in MHz, in frequency order.
    Curated view of `/adif/enumerations/band`."""
    v = version_or_current(adif_version)
    data, _ = paged(request, response,
                    sql.SQL("SELECT {} FROM adif.band WHERE adif_version = %s").format(pick("band", [
                        ("band", "''"), ("lower_freq_mhz", "NULL::numeric"), ("upper_freq_mhz", "NULL::numeric"),
                        ("import_only", FLAG)])), (v,),
                    ["band", "lower_freq_mhz", "upper_freq_mhz"], ["lower_freq_mhz", "band"], limit, offset, q)
    return data


@app.get(f"{API}/adif/modes", response_model=list[Mode], tags=["adif"], responses=PAGED)
def modes(request: Request, response: Response, adif_version: Optional[str] = VersionParam,
          limit: Optional[int] = LimitParam, offset: int = OffsetParam, q: Optional[str] = SearchParam) -> list[dict]:
    """ADIF's Mode enumeration, each with its submodes (e.g. MFSK → FT4). A search matches submodes
    too, so `q=ft4` finds MFSK. Curated view of `/adif/enumerations/mode`."""
    v = version_or_current(adif_version)
    data, _ = paged(request, response,
                    sql.SQL("SELECT *, coalesce((SELECT array_agg(s.submode ORDER BY s.submode) FROM adif.submode s "
                            "WHERE s.adif_version = %s AND s.mode = m.mode), '{{}}') AS submodes "
                            "FROM (SELECT {} FROM adif.mode m WHERE m.adif_version = %s) m").format(pick("mode", [
                        ("mode", "''"), ("description", "NULL::text"), ("import_only", FLAG)], alias="m")), (v, v),
                    ["mode", "description", "submodes"], ["mode"], limit, offset, q)
    return data


@app.get(f"{API}/adif/dxcc", response_model=list[DxccEntity], tags=["adif"], responses=PAGED)
def dxcc(request: Request, response: Response, adif_version: Optional[str] = VersionParam,
         limit: Optional[int] = LimitParam, offset: int = OffsetParam, q: Optional[str] = SearchParam) -> list[dict]:
    """ADIF's DXCC Entity Code enumeration, deleted entities included and marked.
    Curated view of `/adif/enumerations/dxcc_entity_code`."""
    v = version_or_current(adif_version)
    data, _ = paged(request, response,
                    sql.SQL("SELECT {} FROM adif.dxcc_entity_code WHERE adif_version = %s").format(pick("dxcc_entity_code", [
                        ("entity_code", "NULL::integer"), ("entity_name", "''"), ("deleted", FLAG)])), (v,),
                    ["entity_code", "entity_name"], ["entity_code"], limit, offset, q)
    return data


@app.get(f"{API}/adif/contests", response_model=list[Contest], tags=["adif"], responses=PAGED)
def contests(request: Request, response: Response, adif_version: Optional[str] = VersionParam,
             limit: Optional[int] = LimitParam, offset: int = OffsetParam, q: Optional[str] = SearchParam) -> list[dict]:
    """ADIF's Contest_ID enumeration. Curated view of `/adif/enumerations/contest_id`."""
    v = version_or_current(adif_version)
    data, _ = paged(request, response,
                    sql.SQL("SELECT {} FROM adif.contest_id WHERE adif_version = %s").format(pick("contest_id", [
                        ("contest_id", "''"), ("description", "NULL::text"), ("import_only", FLAG)])), (v,),
                    ["contest_id", "description"], ["contest_id"], limit, offset, q)
    return data


@app.get(f"{API}/adif/fields", response_model=list[Field], tags=["adif"], responses=PAGED)
def fields(request: Request, response: Response, adif_version: Optional[str] = VersionParam,
           limit: Optional[int] = LimitParam, offset: int = OffsetParam, q: Optional[str] = SearchParam) -> list[dict]:
    """ADIF's fields (`fields.json`): the vocabulary every IONIS-AI column is defined against."""
    v = version_or_current(adif_version)
    data, _ = paged(request, response,
                    sql.SQL("SELECT {} FROM adif.field WHERE adif_version = %s").format(pick("field", [
                        ("field_name", "''"), ("data_type", "''"), ("enumeration", "NULL::text"),
                        ("description", "NULL::text"), ("import_only", FLAG)])), (v,),
                    ["field_name", "data_type", "enumeration", "description"], ["field_name"], limit, offset, q)
    return data


@app.get(f"{API}/adif/datatypes", response_model=list[DataType], tags=["adif"], responses=PAGED)
def datatypes(request: Request, response: Response, adif_version: Optional[str] = VersionParam,
              limit: Optional[int] = LimitParam, offset: int = OffsetParam, q: Optional[str] = SearchParam) -> list[dict]:
    """ADIF's data types (`datatypes.json`: GridSquare, Date, Number, ...)."""
    v = version_or_current(adif_version)
    data, _ = paged(request, response,
                    sql.SQL("SELECT {} FROM adif.datatype WHERE adif_version = %s").format(pick("datatype", [
                        ("data_type_name", "''"), ("data_type_indicator", "NULL::text"), ("description", "NULL::text"),
                        ("minimum_value", "NULL::text"), ("maximum_value", "NULL::text"), ("import_only", FLAG)])), (v,),
                    ["data_type_name", "data_type_indicator", "description"], ["data_type_name"], limit, offset, q)
    return data


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


def source_file(table: str) -> str:
    """The file in ADIF's resource zip this enumeration is published as (SPEC R16)."""
    return f"enumerations_{table}.json"


@app.get(f"{API}/adif/enumerations", response_model=list[EnumerationSummary], tags=["adif"])
def enumerations(adif_version: Optional[str] = VersionParam) -> list[dict]:
    """Every ADIF enumeration, with its record count for the version (25 for ADIF 3.1.x), its
    canonical route segment (`table`) and the file ADIF publishes it as."""
    v = version_or_current(adif_version)
    out = []
    for name, t in enumeration_tables().items():
        c = rows(sql.SQL("SELECT count(*) AS n, count(*) FILTER (WHERE import_only) AS io FROM adif.{} "
                         "WHERE adif_version = %s").format(sql.Identifier(t)), (v,))[0]
        out.append({"name": name, "table": t, "file": source_file(t), "records": c["n"], "import_only_records": c["io"]})
    return sorted(out, key=lambda e: e["name"].lower())


_RESERVED = {"adif_version", "limit", "offset", "q"}


@app.get(f"{API}/adif/enumerations/{{name}}", response_model=Enumeration, tags=["adif"], responses=PAGED)
def enumeration(name: str, request: Request, response: Response, adif_version: Optional[str] = VersionParam,
                limit: Optional[int] = LimitParam, offset: int = OffsetParam, q: Optional[str] = SearchParam) -> dict:
    """One ADIF enumeration, with the columns ADIF defines for it. **The canonical route segment is
    the table name**, ADIF's name in lower case (e.g. `secondary_administrative_subdivision`), which
    is also the suffix of the file ADIF publishes it as; ADIF's own spelling
    (`Secondary_Administrative_Subdivision`) is accepted too, in any case. Anything else is 404.

    Paged with `limit` / `offset`, searched with `q`, and **filtered exactly on any of its columns**
    by name, e.g. `?dxcc_entity_code=15&deleted=false`. A filter naming a column the enumeration
    does not have is refused (400) rather than ignored."""
    v = version_or_current(adif_version)
    tables = enumeration_tables()
    by_table = {t: n for n, t in tables.items()}
    key = name.lower()
    table = key if key in by_table else next((t for n, t in tables.items() if n.lower() == key), None)
    if table is None:
        raise HTTPException(404, f"No ADIF enumeration named {name!r}")
    cols = rows(
        "SELECT column_name AS name, data_type AS type FROM information_schema.columns "
        "WHERE table_schema = 'adif' AND table_name = %s AND column_name NOT IN ('adif_version', 'record') "
        "ORDER BY ordinal_position", (table,))
    names = [c["name"] for c in cols]
    where = {}
    for k, val in request.query_params.multi_items():
        if k in _RESERVED:
            continue
        if k not in names:
            raise HTTPException(400, f"{by_table[table]} has no column {k!r}; filterable: {', '.join(names)}")
        where[k] = val
    base = sql.SQL("SELECT {} FROM adif.{} WHERE adif_version = %s").format(
        sql.SQL(", ").join(sql.Identifier(c) for c in names), sql.Identifier(table))
    data, total = paged(request, response, base, (v,), names, ["record_key"], limit, offset, q, where)
    return {"name": by_table[table], "table": table, "file": source_file(table), "adif_version": v,
            "columns": cols, "rows": data, "total": total, "limit": limit, "offset": offset}


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
