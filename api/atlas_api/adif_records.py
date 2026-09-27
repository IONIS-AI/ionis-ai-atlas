"""Read ADIF's ADI format and check records against an ADIF version loaded in the database.

The checker behind SPEC R13 (a personal log is validated against the `adif` schema's own
definitions) and R17 (a new ADIF version is data, not code). Its first consumer is ADIF's own test
file: ADIF publishes, per version, synthetic QSOs that use every field and every non-deleted,
non-import-only enumeration value, so checking them must produce no finding at all.

What is checked, all of it read from the database rather than written here:
  * every field is an ADIF field of that version, a header USERDEF, or an APP_ field;
  * a USERDEF's own constraint from the header ({a,b,c} values or a {min:max} range);
  * every enumerated value is one of the enumeration's codes, case-insensitively, as ADIF says.
    The code column is derived, not listed: it is the column whose value begins ADIF's record key
    on every row (`20m`, `PM.15` for a code that repeats). A reference like
    Primary_Administrative_Subdivision[DXCC] narrows to rows whose column named after the
    referenced field's enumeration table (`dxcc_entity_code`) equals that field's value.

Severity follows ADIF's data types: a field typed Enumeration (or an enumerated list) must use a
listed value, so anything else is REJECTED; a String that merely references an enumeration
(CONTEST_ID, SUBMODE, MY_COUNTRY) may carry other values, so a miss is a WARNING. A deleted or
import-only value is a WARNING: ADIF accepts it on import and forbids writing it.

Two references name no table and are ADIF's own rules: Country (a DXCC entity name) and
Sponsored_Award (an award whose name begins with a sponsor's prefix). Any other reference to a
table that does not exist is REJECTED as unknown, so a new kind of rule in a future ADIF version
fails loudly instead of passing unchecked.

Out of scope here: data-type formats (Date, Time, GridSquare, Location, number ranges).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

REJECTED, WARNING = "rejected", "warning"
_TAG = re.compile(r"<([A-Za-z0-9_]+)(?::(\d+)(?::([A-Za-z]))?)?>")
_NOT_ENUMS = ("release", "current", "datatype", "field")


# --- ADI ---------------------------------------------------------------------------------------
@dataclass
class Adi:
    header: dict[str, tuple[str, str | None]]   # NAME -> (value, type indicator)
    records: list[dict[str, str]]                # NAME (upper case) -> value, in file order


def parse_adi(text: str) -> Adi:
    """ADI is length-prefixed: a value is exactly the next LEN characters, so it may hold '<',
    line breaks or anything else, and must never be found by splitting on text. A header exists
    exactly when the file does not begin with '<'. Field names are case-insensitive."""
    header: dict[str, tuple[str, str | None]] = {}
    records: list[dict[str, str]] = []
    record: dict[str, str] = {}
    in_header = not text.startswith("<")
    pos = 0
    while (m := _TAG.search(text, pos)) is not None:
        name = m.group(1).upper()
        if m.group(2) is None:                      # a bare tag: <EOH> or <EOR>
            pos = m.end()
            if name == "EOH":
                in_header = False
            elif name == "EOR" and not in_header:
                if record:
                    records.append(record)
                record = {}
            continue
        end = m.end() + int(m.group(2))
        value, pos = text[m.end():end], end
        if in_header:
            header[name] = (value, m.group(3))
        else:
            record[name] = value
    return Adi(header, records)


# --- USERDEF -------------------------------------------------------------------------------------
@dataclass
class UserDef:
    type: str | None
    values: set[str] | None = None                 # {A,B,C}, upper case
    range: tuple[float, float] | None = None       # {min:max}


def userdefs(header: dict[str, tuple[str, str | None]]) -> dict[str, UserDef]:
    out = {}
    for key, (value, typ) in header.items():
        if not key.startswith("USERDEF"):
            continue
        name, _, spec = value.partition(",")
        ud = UserDef(typ)
        if spec.startswith("{") and spec.endswith("}"):
            body = spec[1:-1]
            if ":" in body and "," not in body:
                lo, hi = body.split(":")
                ud.range = (float(lo), float(hi))
            else:
                ud.values = {v.strip().upper() for v in body.split(",")}
        out[name.strip().upper()] = ud
    return out


# --- the reference: one ADIF version, from the database -----------------------------------------
@dataclass
class Enumeration:
    name: str
    table: str
    code_column: str
    index: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))  # CODE -> rows


@dataclass
class Reference:
    version: str
    fields: dict[str, dict]            # FIELD_NAME -> {data_type, enumeration}
    enums: dict[str, Enumeration]      # lower-case ADIF name -> Enumeration
    tables: dict[str, Enumeration]     # table -> Enumeration

    @classmethod
    def load(cls, conn, version: str) -> "Reference":
        """Everything from the loaded tables of `version`. `conn` is a psycopg connection."""
        cur = conn.cursor()
        cur.execute("SELECT field_name, data_type, enumeration FROM adif.field WHERE adif_version = %s", (version,))
        fields = {r[0].upper(): {"data_type": r[1] or "", "enumeration": r[2]} for r in cur.fetchall()}
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'adif' "
                    "AND table_type = 'BASE TABLE' AND NOT (table_name = ANY(%s))", (list(_NOT_ENUMS),))
        enums, tables = {}, {}
        for (table,) in cur.fetchall():
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'adif' "
                        "AND table_name = %s AND column_name NOT IN ('adif_version', 'record') "
                        "ORDER BY ordinal_position", (table,))
            cols = [r[0] for r in cur.fetchall()]
            cur.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)}, record->>%s '
                        f'FROM adif."{table}" WHERE adif_version = %s', ("Enumeration Name", version))
            rows = [dict(zip(cols + ["_name"], r)) for r in cur.fetchall()]
            if not rows:
                continue
            code = _code_column(rows, cols)
            e = Enumeration(rows[0]["_name"] or table, table, code)
            for r in rows:
                e.index[str(r[code]).upper()].append(r)
            enums[e.name.lower()] = e
            tables[table] = e
        return cls(version, fields, enums, tables)


def _code_column(rows: list[dict], cols: list[str]) -> str:
    """The column holding the enumeration's code: the one whose value begins ADIF's record key on
    every row ('20m', 'PM.15' where a code repeats). Derived, so a new ADIF version's enumerations
    need no code here (SPEC R17)."""
    for c in cols:
        if c in ("record_key", "import_only", "deleted", "comments"):
            continue
        if all(r[c] is not None and (r["record_key"] == str(r[c]) or r["record_key"].startswith(f"{r[c]}."))
               for r in rows):
            return c
    raise ValueError(f"no column of {rows[0].get('_name')} matches its record keys")


# --- checking -----------------------------------------------------------------------------------
@dataclass
class Finding:
    record: int          # 1-based position in the file
    field: str
    value: str
    severity: str        # REJECTED | WARNING
    reason: str


_REF = re.compile(r"^\s*([A-Za-z_]+)(?:\[([A-Za-z_]+)\])?\s*$")


def check(ref: Reference, adi: Adi) -> list[Finding]:
    out: list[Finding] = []
    uds = userdefs(adi.header)
    for i, rec in enumerate(adi.records, 1):
        for name, value in rec.items():
            out += _check_field(ref, uds, rec, i, name, value)
    return out


def _check_field(ref, uds, rec, i, name, value) -> list[Finding]:
    bad = lambda sev, why: [Finding(i, name, value, sev, why)]
    if name.startswith("APP_"):
        return []
    if name in uds:
        ud = uds[name]
        if ud.values is not None and value.upper() not in ud.values:
            return bad(REJECTED, f"not one of the header's USERDEF values {sorted(ud.values)}")
        if ud.range is not None:
            try:
                ok = ud.range[0] <= float(value) <= ud.range[1]
            except ValueError:
                ok = False
            if not ok:
                return bad(REJECTED, f"outside the header's USERDEF range {ud.range}")
        return []
    f = ref.fields.get(name)
    if f is None:
        return bad(REJECTED, f"not an ADIF {ref.version} field, USERDEF or APP_ field")
    if not f["enumeration"]:
        return []
    dtype = f["data_type"]
    is_list = "List" in dtype
    strict = is_list or dtype.startswith("Enumeration")
    refs = [m.groups() for m in (_REF.match(p) for p in f["enumeration"].split(",")) if m]
    findings = []
    for item in ([v for v in value.split(",") if v] if is_list else [value]):
        code, _, media = item.partition(":")
        code = code.strip()
        verdict = _lookup(ref, refs, rec, code, strict)
        if media:                                   # a credit, e.g. DXCC:CARD&LOTW
            qm = ref.enums.get("qsl_medium")
            for m in media.split("&"):
                if qm is None or m.strip().upper() not in qm.index:
                    verdict = (False, f"QSL medium {m!r} is not in QSL_Medium")
        ok, why = verdict
        if not ok:
            findings.append(Finding(i, name, value, REJECTED if strict else WARNING, why))
        elif why:
            findings.append(Finding(i, name, value, WARNING, why))
    return findings


def _lookup(ref: Reference, refs, rec, code: str, strict: bool) -> tuple[bool, str]:
    """(valid, note). note is set for a valid but deleted or import-only value."""
    whys = []
    for name, ctx in refs:
        key = name.lower()
        if key == "country":                        # ADIF: a DXCC entity name; no table of its own
            e = ref.enums.get("dxcc_entity_code")
            if e and any(str(r["entity_name"]).upper() == code.upper() for rows in e.index.values() for r in rows):
                return True, ""
            whys.append(f"{code!r} is not a DXCC entity name (Country)")
            continue
        if key == "sponsored_award":                # ADIF: begins with an Award_Sponsor's prefix
            s = ref.enums.get("award_sponsor")
            if s and any(code.upper().startswith(p) for p in s.index):
                return True, ""
            whys.append(f"{code!r} begins with no Award_Sponsor prefix")
            continue
        e = ref.enums.get(key)
        if e is None:
            whys.append(f"{name} is not an enumeration in ADIF {ref.version}")
            continue
        rows = e.index.get(code.upper(), [])
        if ctx:
            # Scope to the record's context FIRST (e.g. the subdivisions of its DXCC entity). ADIF
            # enumerates subdivisions for some entities only: Secondary_Administrative_Subdivision
            # is Alaska's alone, so a USA CNTY ("MA,Middlesex") has no list to be checked against.
            # An empty scope is accepted only when (a) the context value is itself valid (DXCC 291
            # is a real entity; MODE=OFDM is not a mode in 3.1.6) and (b) the field is strictly
            # typed: for a String like SUBMODE, "ADIF lists none for this mode" stays a warning.
            given = rec.get(ctx.upper())
            ctx_field = ref.fields.get(ctx.upper())
            target = ref.enums.get(((ctx_field or {}).get("enumeration") or "").lower())
            sample = next(iter(e.index.values()))[0]
            if given and target and target.table in sample:
                scoped = [r for rs in e.index.values() for r in rs if str(r[target.table]).upper() == given.upper()]
                if not scoped:
                    if given.upper() not in target.index:
                        whys.append(f"{ctx}={given} is not in {target.name}")
                        continue
                    if strict:
                        return True, ""
                    whys.append(f"ADIF lists no {e.name} for {ctx}={given}")
                    continue
                rows = [r for r in scoped if str(r[e.code_column]).upper() == code.upper()]
                if not rows:
                    whys.append(f"{code!r} is not a {e.name} of {ctx}={given}")
                    continue
        if not rows:
            whys.append(f"{code!r} is not in {e.name}")
            continue
        if all(r.get("deleted") for r in rows):
            return True, f"{code!r} is a deleted {e.name} value"
        if all(r.get("import_only") for r in rows):
            return True, f"{code!r} is an import-only {e.name} value"
        return True, ""
    return False, "; ".join(whys)
