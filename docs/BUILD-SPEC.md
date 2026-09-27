<!--
This is the authoritative build specification for IONIS-AI Atlas (Judge, 2026-09-27: the spec
moved here from fleet-ops packaging/fleet-llm-bench/projects/atlas-web/SPEC.md). It began as a copy
of that internal document, with infrastructure identifiers -- machine names, secret locations and
the lab's own PKI plumbing -- replaced by the capability they stand for, so that anyone using these
images can read it. Changes are made here, by PR.
-->

# IONIS-AI Propagation Atlas (Web) — build specification

You are building a production-grade web application. This document is the complete requirement.

## What it is

The IONIS-AI collection publishes **propagation signatures**: 175M+ aggregated observations of
which HF radio paths were open, on which band, at which UTC hour and month of year, with what
signal strength and reliability — distilled from 14+ billion raw spots.

This application is how people explore that data. It is the public face of the collection: it
should look and behave like a professional analytics product, not a demo.

## Stack

- **React 18+ with TypeScript**, built with **Vite**. All charts and maps in **Apache ECharts**.
- **The API: Python 3.12, FastAPI, psycopg 3**, in the same image as the React build. The browser
  never talks to the database; the API holds the only database connection and exposes bounded,
  read-only queries. Python is the lab's default language.
- **PostgreSQL with pgvector**, in its own image; the published data arrives in data images, one per
  dataset (see Deployment).
- **Vitest** for the front end, and the API's own test suite.

### The API contract

- **Versioned under `/api/v1/`.** The OpenAPI description at `/api/v1/openapi.json` is a published
  contract: changes are additive only, and anything breaking goes to `/api/v2/`.
- **The front end's API client is generated from that OpenAPI description** (TypeScript types and
  calls), never written by hand, so the React app and the API cannot drift.
- **Swagger UI at `/api/docs`, self-hosted.** Its JavaScript and CSS ship inside the image and are
  served locally. FastAPI's default loads them from a CDN, which the no-third-party-calls rule
  forbids; the self-hosted form also works offline. ReDoc is off, so there is one place to look.
- **"Try it out" is safe by construction:** every endpoint is read-only, the database role cannot
  write, and the SQL console has a timeout and a row limit. A public hosted instance adds rate
  limiting in front; a user's own `docker compose` copy needs none.

### Base images

**Red Hat UBI 9** for every image (the lab is RHEL throughout, and UBI images are freely
redistributable; Rocky is the lab's host OS, not an image base). The database image installs PostgreSQL 17 and pgvector from the PGDG
repository; the app image uses UBI's Python 3.12, with Node 20 only in the build stage for the React
bundle.

### Why this

**Atlas talks directly to the database.** There are no published files, no browser query engine and
no hosted path (decided 2026-09-26). Everything a user needs arrives as Docker images and runs with
one command.

**PostgreSQL with pgvector** puts the dimension data (ADIF's enumerations and the IONIS-AI dimensions)
in the same database as the analytics data it describes. Joins and foreign keys work across them,
and the signature embeddings sit beside them as vectors. It is the lab's own stack: PG-1 already
runs PostgreSQL with pgvector.

### Dependency licensing: not negotiable

Every dependency must be permissively licensed and free to build. A build that needs a licence
key, a paid tier, or a commercial component is a failed build. This ships under Apache-2.0.

## The data

**The published IONIS-AI collection, as tables in PostgreSQL.** What it contains is decided in
`ionis-core/docs/COLLECTION-V2-SPEC.md` (Phase 1). Every field is defined in
`ionis-core/docs/IONIS-DATA-SPEC.md`: ADIF 3.1.7, plus the IONIS-AI extension. Atlas reads the
database as published and never writes to it.

| schema | holds |
|---|---|
| `adif` | ADIF's data types, fields and 25 enumerations, versioned by `adif_version`; `adif.current` names the version in use. Growing to the rest of ADIF's published resource zip (files, entity geography, test QSOs) per `IONIS-DATA-SPEC.md`. **ADIF is the base every other schema builds on** |
| `ionis` | IONIS-AI dimensions (DXpeditions, contests, grid centroids, the lab band code), with foreign keys into `adif` |
| `collection` | the published signatures, partitioned by band, plus `collection.manifest`: one row per dataset |

Every signature row carries:

| column | meaning |
|---|---|
| `my_gridsquare_4`, `gridsquare_4` | 4-character Maidenhead locators, in ADIF's roles: the reporting station and the other station. **Not `tx`/`rx`**: a QSO has no transmitter/receiver distinction, because both stations transmit |
| `observation_type` | `reception_report` \| `qso`. Mandatory: `spot_count` and `reliability` mean different things across it |
| `band` | **lab** band code, 102 = 160 m through 111 = 10 m (`ionis.band_id_lab`). *Not* an ADIF field; ADIF defines no numeric band id |
| `hour` | UTC hour, 0 to 23. A climatology bucket, not a time |
| `month` | 1 to 12. A climatology bucket, not a date |
| `signal_metric` | the signal figure. **Its meaning depends on `metric_kind`** |
| `metric_kind` | `wspr_snr` \| `rbn_skimmer` \| `pskr_snr` \| `qso_proxy` |
| `spot_count` | how many observations this row aggregates |
| `snr_std` | standard deviation |
| `reliability` | 0.0 to 1.0 |
| `avg_sfi`, `avg_kp` | solar flux and Kp over the aggregated observations |

**`metric_kind` is why there is no `median_snr` column.** In v1 that one name carried four
incomparable quantities: WSPR's measured SNR (−99 to 58.5), RBN's skimmer scale (−8 to 80), PSKR's
(−30 to 30), and contest's `qso_proxy` (0 to 10), which is a "worked / worked easily" figure and
**not a signal report at all**. Averaging across kinds, or plotting them on one axis, produces a
number that means nothing. The application must refuse to do it (R5).

**Distance and bearing are computed from the grid pair**, never stored.

**Coverage comes from `collection.manifest`, never from knowledge in the code.** Each row declares
the dataset, schema version, `metric_kind`, row count, bands present, month span, era covered and
freeze date. The collection is HF only (bands 102 to 111), PSKR may cover a single month, and the
collection is frozen at a stated date while the lab has moved on. R7 is satisfied by reading the
manifest, not by remembering.

**Inspect the database before designing against it:** partitions, indexes and per-dataset coverage
determine which queries are viable.

## Deployment: Docker images on docker.io

How the collection is published is specified in `ionis-core/docs/COLLECTION-V2-SPEC.md` §7. This
section is what Atlas needs from it.

```yaml
services:
  atlas:
    image: ki7mt/ionis-ai-atlas:<version>
    ports: ["127.0.0.1:8080:8080"]
    environment:
      ATLAS_DB_URL: postgresql://atlas_ro@db:5432/ionis
    depends_on: { db: { condition: service_healthy } }
    volumes:
      - ./mylogs:/data/personal:ro                   # optional: your own ADIF (R13)
  db:
    image: ki7mt/ionis-ai-atlas-db:<version>
    volumes: [pgdata:/var/lib/pgsql/17/data]
  data-wspr:                                         # one service per dataset
    image: ki7mt/ionis-ai-atlas-data-wspr:<version>
    depends_on: { db: { condition: service_healthy } }
    restart: "no"
volumes:
  pgdata:
```

`docker compose up`, then `http://localhost:8080`. That is the whole install, on Docker Desktop or
Docker Engine. Every image is pinned to an exact version in the published compose file.

**Three kinds of image, versioned independently**, because they change at different rates:

| image | holds | changes |
|---|---|---|
| `ionis-ai-atlas` | the application: the React build and the FastAPI API | often |
| `ionis-ai-atlas-db` | the engine: PostgreSQL 17 + pgvector, its tuning, and the reference data (`adif`, `ionis` dimensions) | rarely |
| `ionis-ai-atlas-data-<dataset>` | one dataset: its `pg_dump` and its `collection.manifest` row | when that dataset is added or regenerated |

An application fix is a small pull, and adding a dataset downloads that dataset and nothing else.

**The database volume is a cache, and every start reconciles it.** Docker seeds a named volume from
an image only when the volume is new, so anything baked into an image's data directory would stop
updating after the first run. Therefore nothing is trusted to arrive that way:

- **The engine applies the reference data by version at every start.** It carries the ADIF load
  and applies any ADIF version the database does not yet hold. ADIF's tables are keyed on
  `adif_version`, so a new version is added beside the old one, never replaced.
- **Each data image restores its dataset only if that dataset at that version is absent**, then
  records it in `collection.manifest` and exits.
- **Everything in the volume can be rebuilt from the images.** When the engine's PostgreSQL major
  version differs from the volume's, the engine rebuilds it from the reference data and the data
  images rather than attempting an in-place upgrade.

The result is that a pull followed by `docker compose up` always serves exactly what the pinned
images contain, and a user never deletes a volume by hand.

**Application and data version independently.** The application declares which collection schema
versions it can read, and says so plainly when handed one it cannot.

| | repositories | visibility |
|---|---|---|
| **dev** | **one** repository, `ki7mt/ionis-ai-atlas-dev`, the image kind in the tag: `app-<sha>`, `db-<sha>`, `data-<dataset>-<sha>` | private |
| **prod** | `ki7mt/ionis-ai-atlas`, `ki7mt/ionis-ai-atlas-db`, `ki7mt/ionis-ai-atlas-data-<dataset>` | public |

One docker.io account, `ki7mt` (decided 2026-09-26). **dev is a full rehearsal of the release**,
not only a way to run the app: both architectures in one build, a multi-arch tag, then a clean pull.
prod runs the identical process and differs only in repository layout and visibility. **A release is
a commit tagged `vX.Y.Z`**, published to the public repositories as `:X.Y.Z` and pinned in the
release's `compose.yaml`; it installs with no account and no login (the project owner, 2026-09-27: "nothing that
needs to stay private").
Docker Hub's free plan allows one private repository, so dev uses one (decided 2026-09-27); every
other repository is public from the start.
Day to day, `make dev` builds from a checkout and runs without any registry.

**Requirements on the images:** OCI-generic, so `podman` works rootless and unchanged. The
application and engine are multi-arch, `linux/amd64` and `linux/arm64`, built together in one run on a
machine whose container engine can emulate the other architecture, so one machine and one command
publish a release. A data image is architecture-independent, built once, and published from
wherever the data lives. Tags are immutable. Every image
carries an SBOM and build provenance as registry attestations. **Image signing is planned
(IONIS-AI/ionis-ai-atlas#8), not required to release** (the project owner, 2026-09-27: signing is an option, not
a gate). The push credential is held in a secret manager and read at publish time into a temporary Docker
configuration that is deleted afterwards, never a lasting `docker login`.

## Security

**Atlas holds a SQL console (R14) and, optionally, the user's own log (R13).** The realistic threat
to a local app is not someone on the wire. It is a hostile web page in the user's own browser
reaching `localhost:8080`.

**HTTP on localhost; HTTPS anywhere else, enforced.**

- Bound to `127.0.0.1` (the default), Atlas serves **HTTP**. The traffic never leaves the machine,
  and browsers treat `http://localhost` as a secure context.
- Bound to any other address, Atlas serves **HTTPS only**, and **refuses to start** without a
  certificate and key. Plain HTTP on a network is not an option to document against; it cannot
  be configured.

**Atlas stays out of the certificate business.** It never creates, ships, renews or manages a
certificate.

- The certificate and key are supplied by whoever runs Atlas, mounted read-only (for example
  `/certs/tls.crt`, `/certs/tls.key`): an operator's from their own certificate authority and
  renewal agent, or a public hostname's from Let's Encrypt through a reverse proxy in front of
  Atlas. Atlas contains no ACME client.
- Before serving, Atlas checks that the key matches the certificate, that the certificate is
  currently valid, and that it covers the configured hostname, and refuses to start if any check
  fails. It warns in its log when the certificate is within 14 days of expiry, and reads a renewed
  certificate on restart.
- **No certificate or key is ever in an image, and Atlas never generates a self-signed one.** A key
  inside a public image is public, and a self-signed certificate teaches the user to click through
  a warning.

**The browser boundary:**

- **Host allowlist.** Requests are answered only for `localhost`, `127.0.0.1` and any hostname the
  operator configures; any other `Host` is refused. This closes DNS rebinding, which would
  otherwise let a hostile page use the SQL console or read the personal log.
- **Security headers** on every response: a strict `Content-Security-Policy` allowing only Atlas's
  own origin (possible because everything is self-hosted), `X-Content-Type-Options: nosniff`,
  `frame-ancestors 'none'`, and a `Referrer-Policy`.
- **No CORS.** Atlas's front end is served by Atlas's API, so nothing needs to be allowed.

**The containers:** every container runs as a non-root user, with all capabilities dropped and
`no-new-privileges`; the application's filesystem is read-only; resource limits are set; the
database port is never published; the application reaches the database only on the private
compose network. That link carries no TLS because it never leaves the host; if the database is
ever moved to another host, it gets TLS then.

**The images:** scanned for known vulnerabilities before every push, with a push failing on an
unresolved critical finding; **planned, not yet required to release** (the project owner, 2026-09-27; IONIS-AI/ionis-ai-atlas#18); rebuilt when UBI publishes security updates, so a published version keeps
receiving fixes; with an SBOM and build provenance, and signing planned (above). Nothing inside the images
disables certificate verification for outbound connections.

**Tests:** a test **shall** fail if a request with a foreign `Host` is answered, if any response
lacks the security headers, or if Atlas starts on a non-localhost address without a valid
certificate.

### Target machine

**Atlas must run well on a current mid-range laptop: 4 cores, 16 GB RAM, SSD.** The two containers
together are held to **4 CPUs and 8 GB**, leaving the rest to the machine's owner, and every view
responds within a few seconds at full published size under those limits. PostgreSQL's configuration
ships in the image, tuned for that target; users never tune anything.

The load test that proves this (R8) runs with exactly those limits applied (`cpus: 4`, `mem_limit:
8g`). If a view misses, the table design is fixed: partitions, indexes, or a published rollup. The
target does not move. If Postgres alone cannot meet it for some view, the fallback stays inside the
same database: the `pg_duckdb` extension (MIT) for columnar execution.

Disk is stated in the release notes and is set by what the collection publishes.

## The shell

Before the views: this is one persistent frame, not a set of separate pages.

```
+-------------------------------------------------------------------+
| [IONIS-AI Atlas] <- Home   [ ADIF | Solar | Contests | ... ]  API  |  <- sections
+----------------+--------------------------------------------------+
| «              |  Secondary_Administrative_Subdivision            |
| Data types     |  enumerations_secondary_administrative_...json   |
| Fields         |  [ search....... ] [ entity v ] [ deleted v ]    |  <- filters for THIS view
| Enumerations   |  +--------------------------------------------+  |
|  Ant Path      |  | table                                      |  |
|  ARRL Section  |  |                                            |  |
|  Band          |  +--------------------------------------------+  |
|  ...           |  1-100 of 1,965   < 1 2 3 ... 20 >   [100 v]    |  <- pagination
+----------------+--------------------------------------------------+
  ^ navigation: what to look at, named as the spec names it; collapsible
```

**Primary navigation across the top** switches *section*. Sections are subjects a visitor
arrives with — ADIF, Solar, Contests, DXpeditions, Paths — not chart types. Someone comes here
because they care about DXpeditions, not because they want a scatter plot. **ADIF is the first
section and the base everything else is built on**; IONIS-AI's own data arrives as further
sections, so this strip grows over time. **The brand, "IONIS-AI Atlas", is the link to Home**
(`/`), which is R1.

**The sidebar on the left is navigation, and only navigation:** the list of things this section
contains, in the order and under the names its specification uses (R16), so a reader with the spec
open can find the same thing here. It is **collapsible** (« / ») to give the content region the full
width, remembers that choice per browser, and **starts collapsed at phone width**.

**The content region** renders the active view, **with that view's own filters, search and
pagination above and below it** (R15). What can be filtered depends on what is shown: bands by
frequency, subdivisions by entity, fields by data type. The frame around it does not re-render
when the content does.

*Changed 2026-09-27 (Judge; ionis-ai-atlas#35–#38):* this section previously put the controls in
the sidebar ("the contextual sidebar on the left holds the controls for the active section"). With
one sidebar serving both navigation and filtering, a filter could not be specific to the table it
filters, and the sidebar and the table competed for the same space. Navigation moved left; filters
moved to the view they filter.

The requirements below are capabilities, and they live *inside* sections rather than being
destinations of their own. A path map (R2) is how the Paths section draws its results; source
comparison (R5) is a view within whichever section is being compared. Do not build ten top-level
pages, one per requirement.

### The constraint that matters

**The left rail drives the content region.** That is the entire reason for this arrangement, and
it is the part that is easy to get structurally wrong:

- A filter change updates the content region **without a full page load**.
- The sidebar and the content **share state directly**. They are parts of one application, not
  two applications exchanging messages.

An `<iframe>` produces the right picture and fails this requirement — it is a separate document
with its own scripting context, so every filter change has to be marshalled across a document
boundary, and the back button, deep links and theming all break at that seam. Use one only to
host a genuinely foreign application, never for your own views.

## Requirements

**R1 — Dashboard.** A landing view that makes the scale and shape of the collection immediately
legible: what is present, how much, covering what period and which bands. This is the first
thing a visitor sees; it should make them want to explore. It is **Home** (`/`, reached from the
brand in the top strip), and it also says **what Atlas is**, **which release is running**
(`/api/v1/version`: release and revision, or `dev`), which ADIF versions are loaded and which is
current, and where a developer goes next (`/api/docs`, the OpenAPI description, and how to verify
the signed images).

**R2 — Path map.** Open paths for a chosen band, hour and month, drawn as great-circle arcs on a
world map, encoded by signal strength. Interactive: hover for detail, zoom, select.

**R3 — Path explorer.** For a chosen pair of grid squares: when is this path open? Hour × month,
across bands, with the supporting statistics.

**R4 — Band comparison.** One path or region across all ten HF bands, so an operator can see
which band to use and when.

**R5 — Source comparison, on openness — never on strength.** The same conditions as observed by
WSPR, RBN, contest, DXpedition and PSK Reporter. They use different modes and receivers, so
disagreement is information — present it as such rather than averaging it away.

**The comparison is of whether a path was open**, using presence, `reliability` and `spot_count`,
which mean the same thing everywhere. **Comparing `signal_metric` across `metric_kind` is
forbidden**, and the application **shall refuse** rather than render it with a caveat: a caveat on
a chart is read by nobody, and contest's `qso_proxy` on the same axis as WSPR's dB is not a
comparison, it is a category error with a legend. Include a test that fails if an aggregate
spanning two `metric_kind` values can be produced.

**R6 — Solar context.** How propagation differs between quiet and disturbed conditions, and
across the solar cycle. `avg_sfi` and `avg_kp` are on every signature row; `solar_indices` and
`dscovr` add the time series.

**R6a — Weighting.** Every aggregate across signature rows **shall** be weighted by
`spot_count`. An unweighted mean of `signal_metric` is incorrect: rows aggregate wildly different
observation counts. Include a test that fails against an unweighted implementation.

**R6b — These are climatologies, not timelines.** `hour` and `month` are buckets aggregated
across the full 2008–2026 collection. Every view that displays them **shall** say so on the view.
A reader must not be able to mistake "05:00 UTC, month 6" for a moment in time.

**R6c — Reliability is a first-class figure.** `reliability` (0.0–1.0) **shall** be displayed
wherever a signal figure is displayed. A signal strength without its reliability is an
over-claim.

**R6d — Say what you discarded.** Where rows are dropped — a path whose grid has no centroid, a
row outside a bound — the view **shall** report how many. "59 of 700 mapped; 641 lacked a grid
centroid" is honest; "59 mapped observations" is not.

**R7 — Absent is not empty.** The UI **shall** distinguish three different things: this dataset
is not installed; it is installed but has no observations for these conditions; and it was
observed and the band was closed. A blank must never be ambiguous between them — inside a
rendered view, not only at dataset level.

**The three states are derived from `collection.manifest`, not from knowledge in the code.**
A builder cannot be relied on to remember that the collection is HF-only, or that PSKR may hold
one month, or that it is frozen at a date the lab has since moved past. The manifest states it;
the view reads it. A hardcoded coverage claim is a defect even when it happens to be true.

**R8 — Responsive under real load, on the target machine.** No view may require a table-wide scan.
Every query is bounded by the partition and index it uses, and the UI stays responsive while one
runs. A load test at full published size, with the containers held to 4 CPUs and 8 GB, times every
view and fails if any exceeds its budget.

**R9 — One command to run.** `docker compose up` with the published compose file brings up Atlas,
its database and the published datasets; nothing else is installed, configured or downloaded by
hand. An upgrade is a pull and the same command. A clean pull on a
machine that has never seen the lab **shall** be tested before any release.

**R10 — It must look professional.** Consistent theming, considered spacing and typography, a
coherent colour system, responsive layout, loading and empty states that look designed rather
than default. A reviewer should not be able to tell it was generated.

**R11 — One shell, section routing.** The top strip, the sidebar and the content region persist
across navigation; only the content region changes. Each section is addressable by URL, and the
active filter state is carried in it, so a view can be linked to and restored. This is cheap to
build in from the start and expensive to retrofit, which is why it is a requirement rather than a
nicety.

**R12 — One data source, read-only, through the API.** The API is the only thing that connects to
the database, as a role that can only `SELECT` (`atlas_ro`). The browser never receives a database
credential. Queries live in one place in the API, parameterised, never built by string
concatenation from user input. A test **shall** prove the role cannot write.

**R13 — Your own data.** A log mounted at `/data/personal` **shall** be readable alongside the
collection: ADIF at minimum, validated against the `adif` schema's own definitions, and the
questions that follow from it: which of my contacts fall on paths the collection shows as open,
which of my bands are under-represented, where did I work something the collection says is rare.

The personal log is loaded into a separate schema that the application may write and the published
schemas may not be written from. Personal data **shall never** leave the machine it was mounted on.

**R14 — A SQL console.** Atlas **shall** expose arbitrary read-only SQL against the database, with
the schema visible, run as `atlas_ro` with a statement timeout and a row limit. The console is the
difference between claiming the data is explorable and it being explorable, and the honest answer
to a view the spec did not anticipate.

**R15 — Lists are paged and filtered on the server.** No view renders a whole table, and no list
endpoint makes a client download one.

- **Every list endpoint** accepts `limit` and a position, and returns the page with `total` (rows
  matching the filters), `limit` and the position of the next page. Reference data (ADIF, the
  `ionis` dimensions: thousands of rows) uses `offset`. Collection data (millions to billions)
  uses a **keyset cursor** on the primary key, because `OFFSET` scans every skipped row. `limit`
  defaults to 100 and is capped at 1,000.
- **Filtering and search run in the API**, before the page is cut (`q` for text search, plus
  per-view filters as query parameters). A filter applied in the browser sees only the current
  page, so it silently misses matches: the moment pagination exists, client-side filtering is
  wrong.
- **The contract stays additive** (see *The API contract*): endpoints published before R15 keep
  returning every row when called without `limit`, so no existing consumer breaks. The UI always
  requests pages, and endpoints added from now on page by default.
- The UI shows `1–100 of 1,965`, page controls and a page-size choice, and carries page, size and
  filters in the URL (R11).

*Why:* measured on 0.1.3, the Primary Administrative Subdivision view rendered all 1,965 rows as one
page about 91,000 px tall. That's small next to what's coming: the test QSOs are 6,197 rows per ADIF
version, and the collection is billions.

**R16 — Names come from the specification.** Each thing Atlas shows has **one name**, taken from
the specification that defines it, and that name is visible at every layer, so someone reading the
spec can find it in the UI and the API without a mapping table:

| ADIF (spec and file) | Table | API route | UI route | UI label |
|---|---|---|---|---|
| `Secondary_Administrative_Subdivision` · `enumerations_secondary_administrative_subdivision.json` | `adif.secondary_administrative_subdivision` | `/api/v1/adif/enumerations/secondary_administrative_subdivision` | `/adif/enumerations/secondary_administrative_subdivision` | Secondary Administrative Subdivision |
| `DXCC_Entity_Code` · `enumerations_dxcc_entity_code.json` | `adif.dxcc_entity_code` | `/api/v1/adif/enumerations/dxcc_entity_code` | `/adif/enumerations/dxcc_entity_code` | DXCC Entity Code |
| Fields · `fields.json` | `adif.field` | `/api/v1/adif/fields` | `/adif/fields` | Fields |
| Data Types · `datatypes.json` | `adif.datatype` | `/api/v1/adif/datatypes` | `/adif/datatypes` | Data Types |

- **The route segment is ADIF's name in lower case**, which is also the JSON file's suffix and the
  table name. The API also accepts ADIF's own spelling (`DXCC_Entity_Code`), as it does today.
- **The label is ADIF's name with spaces for underscores.** Each view's heading shows ADIF's exact
  name, the source file and the API route, so the three can be cross-checked from the page.
- The friendly routes published before R16 (`/adif/bands`, `/modes`, `/dxcc`, `/contests`) stay
  (additive contract). OpenAPI marks each as an alias of its canonical route, and the UI uses the
  canonical ones.
- **The same rule holds for everything added later.** The `adif` and `ionis` objects defined in
  `ionis-core/docs/IONIS-DATA-SPEC.md` (release files, entity geography, test QSOs, derived views),
  and IONIS-AI's own data as it arrives, take their names from that document. The surface will grow
  large, and one name per thing is what keeps it navigable.

**R17 — A new ADIF version is data, not code.** Judge, 2026-09-27: *"ADIF releases, we push the new
version, and the UI/API continues on as before."*

- **Adding a version touches only:** its SHA-256 pin (`adif_upstream_sha256.json`), the engine
  image's version list and current pointer (`ADIF_VERSIONS`, `ADIF_CURRENT` in
  `db/load/atlas-db-lib.sh`), and, **only if ADIF changed structure** (a new enumeration, field or
  column), the DDL regenerated by `adif_tier.py ddl`. **Nothing in `api/` or `web/`.**
- **The API and UI derive everything ADIF-specific from the database:** which versions exist, which
  is current, the list of enumerations, their columns and counts. No ADIF version number,
  enumeration name, column list or count appears as a literal in `api/` or `web/`, except the
  curated views (bands, modes, DXCC, contests). Those **degrade rather than break**: a column ADIF
  adds shows in the generic enumeration view and in `record`, and one ADIF removes renders empty
  instead of failing the query.
- **A structural change upgrades an existing database volume**, additively (new tables, new
  columns). It isn't limited to a fresh install: the engine reconciles its volume with the image on
  every start, and that has to include schema, not only rows.
- **Proven by a rehearsal, not asserted:** build an engine carrying **3.1.6 only** and run the API
  and UI test suites; then add **3.1.7** as if it were a new release (it added `OFDM` and four
  submodes) and rerun **the same tests, unchanged**, on a fresh volume **and** on the upgraded 3.1.6
  volume. Both must pass, and the new values must appear without a code change.

*Known gaps at 0.1.3, to close under R17:* the OpenAPI description names "ADIF 3.1.7" literally
(`api/atlas_api/main.py`); the curated views' degrade-not-break behaviour is untested; the volume
upgrade on a structural change is unverified.

## Deliverables

- Source, `package.json`, lockfile committed; `Dockerfile`s for the application, engine and data images, and the `compose.yaml`. The code lives in **`IONIS-AI/ionis-ai-atlas`**
- Clean install, build and passing tests from a fresh checkout, including the load test under the target-machine limits
- `README.md` — run, configure, deploy; every assumption the spec left open
- `FINDINGS.md` — what you learned about the data that the spec did not tell you
- `LICENSE` (Apache-2.0) and SPDX headers

## Rules

- The published schemas open **read-only**. Any write to them is a defect.
- **No third-party network calls.** The application talks to its own API and the API to its own
  database, nothing else: no CDNs, no fonts loaded from elsewhere, no telemetry, no external
  services. Everything needed to run is in the published images.
- No dependency requiring a licence key or a paid tier. The build must succeed from a clean
  checkout with no account.
- Bounded queries only.
- If the spec is ambiguous, choose, and record the choice in `README.md`.
- If the data contradicts the spec, believe the data and say so in `FINDINGS.md`.
