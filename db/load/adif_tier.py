#!/usr/bin/env python3
"""adif_tier.py -- the ADIF reference tier in PostgreSQL, generated from ADIF's own export.

ADIF publishes its specification as machine-readable JSON (all.json in the resource zip on
adif.org.uk). This tool turns that file into the `adif` schema and its rows, so nothing in the
schema is typed in by hand:

    adif.release        one row per loaded ADIF version, with the source file's SHA-256
    adif.datatype       ADIF data types (GridSquare, Date, Number, ...)
    adif.field          ADIF fields (CALL, GRIDSQUARE, FREQ, ...) with type and enumeration
    adif.<enumeration>  one table per enumeration (band, mode, dxcc_entity_code, ...)

RULES IT ENFORCES
  * The input must match a pinned SHA-256 of adif.org's published all.json. A file that differs
    by one byte is refused, so a local edit can never pass as ADIF.
  * Only what ADIF publishes: 25 enumerations. adif-mcp's derived Country table is not an ADIF
    export and is never read (it is not in all.json).
  * Versioned, never replaced: every key includes adif_version. Loading a version that is
    already loaded is refused; versions coexist.
  * Each enumeration row is keyed by ADIF's own record key (e.g. 'PM.15' vs 'PM.15.Deleted.0',
    'KO.296' vs 'KO.522'), because some codes are reused after deletion and some regions change
    over time. A natural code gets a UNIQUE constraint only where ADIF's data makes it unique.
  * Every row keeps the record exactly as published, in `record` (jsonb), beside typed columns.

USAGE
  adif_tier.py ddl  --spec-dir DIR --pins FILE                 > src/pg/10-adif_schema.sql
  adif_tier.py load --spec-dir DIR --pins FILE --version 3.1.7 > load.sql   (psql -1 -f load.sql)
  adif_tier.py audit --spec-dir DIR --pins FILE --version 3.1.7          (SQL that must return 0 rows)
  adif_tier.py set-current --spec-dir DIR --pins FILE --version 3.1.7    (move the lab-wide pointer)

DIR holds one sub-directory per version (316/, 317/), each with ADIF's all.json -- the layout
adif-mcp ships. Standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import sys

# Columns every enumeration header carries that are not data about the value itself.
_SKIP = {"Enumeration Name"}
# Typed columns. Everything else is text, exactly as ADIF writes it.
_BOOL = {"Import-only", "Deleted", "Header Field"}
_NUMERIC = {"Lower Freq (MHz)", "Upper Freq (MHz)"}
_INTEGER = {"Entity Code", "DXCC Entity Code"}
_TIMESTAMP = {"From Date", "Deleted Date", "Start Date", "End Date"}


def col(header: str) -> str:
    """ADIF header -> SQL column name: 'Lower Freq (MHz)' -> lower_freq_mhz, 'Oblast #' -> oblast_no."""
    s = header.replace("#", "no").replace("-", "_")
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s


_FITS = {
    "boolean": lambda v: v in ("true", "false"),
    "numeric": lambda v: re.fullmatch(r"-?(\d+(\.\d*)?|\.\d+)", v),
    "integer": lambda v: re.fullmatch(r"-?\d+", v),
    "timestamptz": lambda v: re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", v),
}
# Effective type per (table, header), decided from the data of EVERY pinned version (set_types).
# A header is typed only if all its values fit; otherwise it stays text, as ADIF wrote it.
# Measured 3.1.6/3.1.7: ARRL_Section's DXCC Entity Code holds lists ('43,202') in 3 rows, so
# there it is text and carries no foreign key.
_TYPES = {}


def declared(header: str) -> str:
    if header in _BOOL:
        return "boolean"
    if header in _NUMERIC:
        return "numeric"
    if header in _INTEGER:
        return "integer"
    if header in _TIMESTAMP:
        return "timestamptz"
    return "text"


def set_types(versions: dict) -> None:
    for adif in versions.values():
        blocks = [("datatype", adif["DataTypes"]), ("field", adif["Fields"])]
        blocks += [(n.lower(), e) for n, e in adif["Enumerations"].items()]
        for table, block in blocks:
            for h in block["Header"]:
                t = declared(h)
                if t == "text":
                    continue
                fits = all(_FITS[t](r[h]) for r in block["Records"].values() if r.get(h) not in (None, ""))
                if not fits or _TYPES.get((table, h)) == "text":
                    _TYPES[(table, h)] = "text"
                else:
                    _TYPES.setdefault((table, h), t)


def sql_type(header: str, table: str = "") -> str:
    return _TYPES.get((table, header), declared(header))


def lit(v, header: str, table: str = "") -> str:
    """A value as a SQL literal of the column's type. ADIF's empty string means absent: NULL."""
    if v is None or v == "":
        return "NULL"
    t = sql_type(header, table)
    if t == "boolean":
        if v not in ("true", "false"):
            raise ValueError(f"{header}: expected true/false, got {v!r}")
        return v.upper()
    if t in ("numeric", "integer", "timestamptz"):
        if not _FITS[t](v):
            raise ValueError(f"{table}.{header}: not {t}: {v!r}")
        return v if t != "timestamptz" else "'" + v + "'"
    return "'" + str(v).replace("'", "''") + "'"


def jlit(obj) -> str:
    return "'" + json.dumps(obj, ensure_ascii=False, sort_keys=True).replace("'", "''") + "'::jsonb"


def load_version(spec_dir: str, pins: dict, vdir: str) -> dict:
    path = os.path.join(spec_dir, vdir, "all.json")
    with open(path, "rb") as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    want = pins["versions"][vdir]["files"]["all.json"]
    if sha != want:
        sys.exit(f"{path}: SHA-256 {sha} does not match adif.org's published {want}. Refusing.")
    adif = json.loads(raw.decode("utf-8-sig"))["Adif"]
    if "Country" in adif["Enumerations"]:
        sys.exit(f"{path}: carries a Country enumeration; ADIF publishes none. Refusing.")
    adif["_sha256"] = sha
    adif["_source"] = pins["versions"][vdir]["source"]
    return adif


def all_versions(spec_dir: str, pins: dict) -> dict:
    versions = {v: load_version(spec_dir, pins, v) for v in sorted(pins["versions"])}
    set_types(versions)
    return versions


def headers(versions: dict, section: str, name: str = None) -> list:
    """Union of a table's headers across versions, in first-seen order, so one DDL serves all."""
    out = []
    for adif in versions.values():
        block = adif[section] if name is None else adif[section].get(name)
        if not block:
            continue
        for h in block["Header"]:
            if h not in _SKIP and h not in out:
                out.append(h)
    return out


def unique_natural_key(versions: dict, name: str, hdrs: list):
    """The smallest column set that is unique and never empty in EVERY version, else None."""
    import itertools

    cand = [h for h in hdrs if h not in ("Import-only", "Comments")]
    for r in (1, 2):
        for combo in itertools.combinations(cand, r):
            ok = True
            for adif in versions.values():
                recs = list(adif["Enumerations"].get(name, {}).get("Records", {}).values())
                vals = [tuple(x.get(c, "") for c in combo) for x in recs]
                if any("" in t for t in vals) or len(set(vals)) != len(vals):
                    ok = False
                    break
            if ok:
                return combo
    return None


def ddl(versions: dict) -> str:
    enums = sorted({n for a in versions.values() for n in a["Enumerations"]})
    out = [
        "-- =============================================================================",
        "-- 10-adif_schema.sql -- the ADIF reference tier (PostgreSQL, PG-1 database `ionis`)",
        "-- GENERATED by scripts/adif_tier.py from ADIF's published all.json for "
        + ", ".join(a["Version"] for a in versions.values())
        + ". Do not edit by hand: regenerate.",
        "-- Every key carries adif_version: versions coexist and a new release is additive.",
        "-- Enumeration rows are keyed by ADIF's own record key; `record` keeps each exactly as published.",
        "-- =============================================================================",
        "",
        "CREATE SCHEMA IF NOT EXISTS adif;",
        "",
        "CREATE TABLE IF NOT EXISTS adif.release (",
        "    adif_version  text PRIMARY KEY,",
        "    status        text NOT NULL,",
        "    released      timestamptz,",
        "    created       timestamptz,",
        "    source_url    text NOT NULL,",
        "    source_sha256 text NOT NULL,",
        "    loaded_at     timestamptz NOT NULL DEFAULT now()",
        ");",
        "",
        "-- The lab-wide CURRENT ADIF version (spec: one pointer; rows pin at write and re-pin only",
        "-- by explicit migration). One row, enforced. Loading a version never moves it: set it",
        "-- deliberately with `adif_tier.py set-current --version X`.",
        "CREATE TABLE IF NOT EXISTS adif.current (",
        "    singleton     boolean PRIMARY KEY DEFAULT TRUE CHECK (singleton),",
        "    adif_version  text NOT NULL REFERENCES adif.release (adif_version),",
        "    set_at        timestamptz NOT NULL DEFAULT now()",
        ");",
        "",
    ]

    def table(name, hdrs, key_cols, extra=""):
        lines = [f"CREATE TABLE IF NOT EXISTS adif.{name} (",
                 "    adif_version text NOT NULL REFERENCES adif.release (adif_version),"]
        lines += [f"    {col(h):<40} {sql_type(h, name)}," for h in hdrs]
        lines.append("    record       jsonb NOT NULL,")
        lines.append(f"    PRIMARY KEY (adif_version, {', '.join(key_cols)}){extra}")
        lines.append(");")
        return lines

    out += table("datatype", headers(versions, "DataTypes"), ["data_type_name"])
    out.append("")
    fh = headers(versions, "Fields")
    out += table("field", fh, ["field_name"])
    out.append("-- No foreign key on data_type: CREDIT_GRANTED / CREDIT_SUBMITTED name two types")
    out.append("-- ('CreditList,AwardList'). The load checks every listed type instead (see load_sql).")
    out.append("")
    fks = []
    for name in enums:
        t = name.lower()
        hdrs = headers(versions, "Enumerations", name)
        out.append(f"-- {name}")
        lines = [f"CREATE TABLE IF NOT EXISTS adif.{t} (",
                 "    adif_version text NOT NULL REFERENCES adif.release (adif_version),",
                 "    record_key   text NOT NULL,"]
        lines += [f"    {col(h):<40} {sql_type(h, t)}," for h in hdrs]
        lines.append("    record       jsonb NOT NULL,")
        lines.append("    PRIMARY KEY (adif_version, record_key)")
        lines.append(");")
        out += lines
        nk = unique_natural_key(versions, name, hdrs)
        if nk:
            cols = ", ".join(col(c) for c in nk)
            out.append(f"CREATE UNIQUE INDEX IF NOT EXISTS {t}_natural ON adif.{t} (adif_version, {cols});")
        else:
            out.append(f"-- {name}: no column set is unique in every version; reference it by record_key.")
        if "DXCC Entity Code" in hdrs and name != "DXCC_Entity_Code" and sql_type("DXCC Entity Code", t) == "integer":
            fks.append((t, "dxcc_entity_code", "adif.dxcc_entity_code (adif_version, entity_code)"))
        elif "DXCC Entity Code" in hdrs and name != "DXCC_Entity_Code":
            out.append(f"-- {name}: dxcc_entity_code holds lists in some rows (e.g. '43,202'); text, no foreign key.")
        out.append("")
    if "Submode" in enums:
        fks.append(("submode", "mode", "adif.mode (adif_version, mode)"))
    out.append("-- Cross-references ADIF itself defines. A load that violates one fails whole.")
    for t, c, ref in fks:
        cn = f"{t}_{c}_fk"
        out.append(f"ALTER TABLE adif.{t} DROP CONSTRAINT IF EXISTS {cn};")
        out.append(f"ALTER TABLE adif.{t} ADD CONSTRAINT {cn} FOREIGN KEY (adif_version, {c}) REFERENCES {ref};")
    out.append("")
    out.append("-- The read-only role sees everything in this schema, now and later.")
    out.append("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ionis_ro') THEN")
    out.append("  GRANT USAGE ON SCHEMA adif TO ionis_ro;")
    out.append("  GRANT SELECT ON ALL TABLES IN SCHEMA adif TO ionis_ro;")
    out.append("  ALTER DEFAULT PRIVILEGES IN SCHEMA adif GRANT SELECT ON TABLES TO ionis_ro;")
    out.append("END IF; END $$;")
    return "\n".join(out) + "\n"


def load_sql(adif: dict) -> str:
    v = adif["Version"]
    out = [f"-- Load ADIF {v} from {adif['_source']} (all.json sha256 {adif['_sha256']}).",
           "-- Run as one transaction (psql -1): all of it lands or none of it does.",
           "INSERT INTO adif.release (adif_version, status, released, created, source_url, source_sha256) VALUES ("
           + ", ".join([lit(v, "x"), lit(adif["Status"], "x"), lit(adif.get("Date"), "Start Date"),
                        lit(adif.get("Created"), "Start Date"), lit(adif["_source"], "x"),
                        lit(adif["_sha256"], "x")]) + ");"]

    def rows(table, block, key=None):
        hdrs = [h for h in block["Header"] if h not in _SKIP]
        cols = ["adif_version"] + (["record_key"] if key else []) + [col(h) for h in hdrs] + ["record"]
        for rk, rec in block["Records"].items():
            vals = [lit(v, "x")] + ([lit(rk, "x")] if key else []) + [lit(rec.get(h), h, table) for h in hdrs] + [jlit(rec)]
            out.append(f"INSERT INTO adif.{table} ({', '.join(cols)}) VALUES ({', '.join(vals)});")

    rows("datatype", adif["DataTypes"])
    rows("field", adif["Fields"])
    # DXCC and Mode first: other enumerations reference them.
    order = sorted(adif["Enumerations"], key=lambda n: (n not in ("DXCC_Entity_Code", "Mode"), n))
    for name in order:
        rows(name.lower(), adif["Enumerations"][name], key=True)
    out.append(list_checks(v))
    return "\n".join(out) + "\n"


# Enumerations ADIF's field definitions name but ADIF does not publish as tables:
#   Country          -- MY_COUNTRY / MY_COUNTRY_INTL; the names are DXCC_Entity_Code's Entity Name
#   Sponsored_Award  -- AWARD_GRANTED / AWARD_SUBMITTED; a sponsor-prefixed free form
# Any OTHER unknown reference fails the load.
_UNPUBLISHED_ENUMS = ("country", "sponsored_award")


def list_checks(v: str) -> str:
    """Integrity a foreign key cannot express (list-valued references), checked inside the load
    transaction: any violation raises and the whole version rolls back."""
    return f"""DO $check$
DECLARE bad text;
BEGIN
  -- every type a field names ('CreditList,AwardList' names two) is an ADIF data type
  SELECT string_agg(f.field_name || ':' || t, ', ') INTO bad
    FROM adif.field f, unnest(string_to_array(f.data_type, ',')) t
   WHERE f.adif_version = '{v}'
     AND NOT EXISTS (SELECT 1 FROM adif.datatype d WHERE d.adif_version = '{v}' AND d.data_type_name = t);
  IF bad IS NOT NULL THEN RAISE EXCEPTION 'ADIF {v}: fields name unknown data types: %', bad; END IF;

  -- every DXCC code in an ARRL section's list ('43,202') is an ADIF DXCC entity
  SELECT string_agg(a.abbreviation || ':' || c, ', ') INTO bad
    FROM adif.arrl_section a, unnest(string_to_array(a.dxcc_entity_code::text, ',')) c
   WHERE a.adif_version = '{v}'
     AND NOT EXISTS (SELECT 1 FROM adif.dxcc_entity_code d WHERE d.adif_version = '{v}' AND d.entity_code = c::integer);
  IF bad IS NOT NULL THEN RAISE EXCEPTION 'ADIF {v}: ARRL sections name unknown DXCC entities: %', bad; END IF;

  -- every enumeration a field names is loaded here, or is one ADIF names but does not publish
  SELECT string_agg(DISTINCT f.field_name || ':' || e, ', ') INTO bad
    FROM adif.field f, unnest(string_to_array(regexp_replace(f.enumeration, '\[[^]]*\]', '', 'g'), ',')) e
   WHERE f.adif_version = '{v}' AND f.enumeration IS NOT NULL
     AND lower(e) NOT IN ({", ".join("'" + x + "'" for x in _UNPUBLISHED_ENUMS)})
     AND NOT EXISTS (SELECT 1 FROM information_schema.tables t WHERE t.table_schema = 'adif' AND t.table_name = lower(e));
  IF bad IS NOT NULL THEN RAISE EXCEPTION 'ADIF {v}: fields name enumerations that are not loaded: %', bad; END IF;
END $check$;"""


def audit_sql(adif: dict) -> str:
    """One SELECT per table; the audit passes when the whole query returns zero rows."""
    v = adif["Version"]
    parts = [f"SELECT 'datatype' t, count(*) got, {len(adif['DataTypes']['Records'])} want FROM adif.datatype WHERE adif_version = '{v}'",
             f"SELECT 'field', count(*), {len(adif['Fields']['Records'])} FROM adif.field WHERE adif_version = '{v}'"]
    for name, e in sorted(adif["Enumerations"].items()):
        parts.append(f"SELECT '{name.lower()}', count(*), {len(e['Records'])} FROM adif.{name.lower()} WHERE adif_version = '{v}'")
    enum_total = sum(len(e["Records"]) for e in adif["Enumerations"].values())
    tables = " UNION ALL ".join(f"SELECT count(*) c FROM adif.{n.lower()} WHERE adif_version = '{v}'" for n in adif["Enumerations"])
    parts.append(f"SELECT 'ALL ENUMERATIONS', (SELECT sum(c) FROM ({tables}) s), {enum_total}")
    parts.append(f"SELECT 'release sha256', (SELECT count(*) FROM adif.release WHERE adif_version = '{v}' AND source_sha256 = '{adif['_sha256']}'), 1")
    return ("-- ADIF " + v + " audit: every table's row count equals the published file's. Zero rows = pass.\n"
            "SELECT * FROM (\n  " + "\n  UNION ALL ".join(parts) + "\n) a WHERE got <> want;\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["ddl", "load", "audit", "set-current"])
    ap.add_argument("--spec-dir", required=True)
    ap.add_argument("--pins", required=True, help="SHA-256 manifest of adif.org's exports")
    ap.add_argument("--version", help="ADIF version for load/audit, e.g. 3.1.7")
    a = ap.parse_args()
    with open(a.pins, encoding="utf-8") as f:
        pins = json.load(f)
    if a.action == "ddl":
        sys.stdout.write(ddl(all_versions(a.spec_dir, pins)))
        return
    if not a.version:
        sys.exit("--version is required for load, audit and set-current")
    if a.action == "set-current":
        v = a.version.replace("'", "")
        sys.stdout.write(
            f"-- Point the lab at ADIF {v}. Fails if {v} is not loaded (foreign key to adif.release).\n"
            f"INSERT INTO adif.current (singleton, adif_version) VALUES (TRUE, '{v}')\n"
            f"ON CONFLICT (singleton) DO UPDATE SET adif_version = EXCLUDED.adif_version, set_at = now();\n")
        return
    vdir = a.version.replace(".", "")
    if vdir not in pins["versions"]:
        sys.exit(f"ADIF {a.version} has no pinned checksum; add it to {a.pins} first")
    adif = all_versions(a.spec_dir, pins)[vdir]  # every pinned version: types are decided across all
    sys.stdout.write(load_sql(adif) if a.action == "load" else audit_sql(adif))


if __name__ == "__main__":
    main()
