"""ADIF's own test QSOs, checked against each loaded ADIF version (#45; SPEC R13, R17).

ADIF publishes, in each version's resource zip, synthetic QSOs using every field and every
non-deleted, non-import-only enumeration value: 6,191 for 3.1.6 and 6,197 for 3.1.7. Checked
against that version's `adif` tables they must raise nothing at all, and checked against the
previous version they must raise exactly what the new version added. That is direct proof that a
loaded version's values are usable with no code change (R17), and the conformance fixture for
personal-log import (R13).

The zip is read from ADIF, verified against the pin the database image was built from
(db/load/adif_upstream_sha256.json), and cached (ATLAS_ADIF_CACHE, default ~/.cache). A zip that
does not match the pin FAILS; only an unreachable adif.org with nothing cached skips.
"""
import hashlib
import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path

import pytest

from atlas_api.adif_records import REJECTED, WARNING, Reference, check, parse_adi

DB = os.environ.get("ATLAS_DB_URL")
pytestmark = pytest.mark.skipif(not DB, reason="ATLAS_DB_URL not set: needs a running Atlas database image")

ROOT = Path(__file__).resolve().parents[2]
PINS = json.loads((ROOT / "db/load/adif_upstream_sha256.json").read_text())
CACHE = Path(os.environ.get("ATLAS_ADIF_CACHE", Path.home() / ".cache/ionis-ai-atlas/adif"))


def resource_zip(version: str) -> zipfile.ZipFile:
    pin = PINS["versions"][version.replace(".", "")]
    path = CACHE / f"{version.replace('.', '')}.zip"
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != pin["zip_sha256"]:
        try:
            raw = urllib.request.urlopen(pin["source"], timeout=60).read()
        except OSError as e:
            pytest.skip(f"ADIF {version} zip not cached and adif.org unreachable: {e}")
        got = hashlib.sha256(raw).hexdigest()
        assert got == pin["zip_sha256"], f"{pin['source']}: SHA-256 {got} is not the pinned {pin['zip_sha256']}"
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return zipfile.ZipFile(path)


def test_file(version: str, ext: str) -> str:
    z = resource_zip(version)
    return z.read(next(n for n in z.namelist() if re.search(rf"/tests/ADIF_[^/]+_test_QSOs_[^/]+\.{ext}$", n))).decode("utf-8")


test_file.__test__ = False  # a helper, not a test


@pytest.fixture(scope="module")
def conn():
    import psycopg
    with psycopg.connect(DB) as c:
        yield c


@pytest.fixture(scope="module")
def versions(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT adif_version FROM adif.release ORDER BY adif_version").fetchall()]


@pytest.fixture(scope="module")
def ref(conn):
    cache = {}
    return lambda v: cache.setdefault(v, Reference.load(conn, v))


def test_every_loaded_version_has_a_pin(versions):
    assert versions and all(v.replace(".", "") in PINS["versions"] for v in versions)


# --- the whole file, per version ---------------------------------------------------------------
def test_the_parser_finds_every_record(versions):
    for v in versions:
        adi_text = test_file(v, "adi")
        records = parse_adi(adi_text).records
        eor = len(re.findall(r"<eor>", adi_text, re.I))
        adx = len(re.findall(r"<RECORD>", test_file(v, "adx")))
        assert len(records) == eor == adx, f"ADIF {v}: parsed {len(records)}, <EOR> {eor}, ADX <RECORD> {adx}"


def test_adifs_own_test_qsos_raise_nothing(versions, ref):
    for v in versions:
        findings = check(ref(v), parse_adi(test_file(v, "adi")))
        assert findings == [], f"ADIF {v}: {len(findings)} findings, first: {findings[:5]}"


def test_a_file_against_the_previous_version_raises_exactly_what_changed(versions, ref):
    """3.1.7 added MODE OFDM and SUBMODEs FREEDATA, FT2, RIBBIT_PIX, RIBBIT_SMS (IONIS-DATA-SPEC.md).
    Its test file checked against 3.1.6's tables must flag those five values and nothing else:
    OFDM rejected (MODE is an Enumeration), the submodes warned (SUBMODE is a String)."""
    if not {"3.1.6", "3.1.7"} <= set(versions):
        pytest.skip("needs 3.1.6 and 3.1.7 loaded")
    findings = check(ref("3.1.6"), parse_adi(test_file("3.1.7", "adi")))
    assert {(f.field, f.value) for f in findings} == {
        ("MODE", "OFDM"), ("SUBMODE", "FREEDATA"), ("SUBMODE", "FT2"), ("SUBMODE", "RIBBIT_PIX"), ("SUBMODE", "RIBBIT_SMS")}
    assert {f.severity for f in findings if f.field == "MODE"} == {REJECTED}
    assert {f.severity for f in findings if f.field == "SUBMODE"} == {WARNING}


# --- each rule must bite ------------------------------------------------------------------------
def field(name: str, value: str, typ: str = "") -> str:
    """One ADI field with its length computed, so a fixture can't be miscounted by hand."""
    return f"<{name}:{len(value)}{':' + typ if typ else ''}>{value}"


def adi(fields: dict, header: str = "") -> str:
    body = "".join(field(k, v) for k, v in fields.items()) + "<EOR>"
    return (f"built for a test {header}<EOH>" if header else "") + body


def findings_for(ref, fields, header=""):
    return [(f.field, f.severity) for f in check(ref("3.1.7"), parse_adi(adi(fields, header)))]


@pytest.mark.parametrize("fields,expect", [
    ({"BAND": "20m"}, []),
    ({"band": "20M"}, []),                                               # names and values: case-insensitive
    ({"BAND": "21m"}, [("BAND", REJECTED)]),
    ({"DXCC": "291"}, []),
    ({"DXCC": "9999"}, [("DXCC", REJECTED)]),
    ({"DXCC": "1", "STATE": "NS"}, []),                                   # Nova Scotia, Canada
    ({"DXCC": "291", "STATE": "NS"}, [("STATE", REJECTED)]),              # not a USA state
    ({"DXCC": "291", "CNTY": "MA,Middlesex"}, []),                        # ADIF lists no USA counties
    ({"DXCC": "6", "CNTY": "AK,Anchorage"}, []),                          # Alaska's list
    ({"DXCC": "6", "CNTY": "AK,Nowhere"}, [("CNTY", REJECTED)]),
    ({"MODE": "MFSK", "SUBMODE": "FT4"}, []),
    ({"MODE": "SSB", "SUBMODE": "FT4"}, [("SUBMODE", WARNING)]),          # a String: advisory
    ({"MODE": "NOTAMODE"}, [("MODE", REJECTED)]),
    ({"FOO": "1"}, [("FOO", REJECTED)]),
    ({"APP_ATLAS_TEST": "anything"}, []),
    ({"CREDIT_SUBMITTED": "CQDX:CARD"}, []),
    ({"CREDIT_SUBMITTED": "CQDX:CARD&LOTW,DXCC"}, []),
    ({"CREDIT_SUBMITTED": "NOPE:CARD"}, [("CREDIT_SUBMITTED", REJECTED)]),
    ({"CREDIT_SUBMITTED": "CQDX:PIGEON"}, [("CREDIT_SUBMITTED", REJECTED)]),
    ({"AWARD_SUBMITTED": "ADIF_CENTURY_BASIC"}, []),
    ({"AWARD_SUBMITTED": "XYZZY_AWARD"}, [("AWARD_SUBMITTED", REJECTED)]),
    ({"MY_COUNTRY": "United States of America"}, []),
    ({"MY_COUNTRY": "Atlantis"}, [("MY_COUNTRY", WARNING)]),
])
def test_each_rule_bites(ref, fields, expect):
    assert findings_for(ref, fields) == expect


@pytest.mark.parametrize("value,expect", [("QRP", []), ("QrpP", []), ("QRX", [("MY_POWER_CATEGORY", REJECTED)])])
def test_a_userdef_list_from_the_header(ref, value, expect):
    header = field("USERDEF1", "MY_POWER_CATEGORY,{QRPP,QRP,QRO}", "E")
    assert findings_for(ref, {"MY_POWER_CATEGORY": value}, header) == expect


@pytest.mark.parametrize("value,expect", [("66", []), ("-50", []), ("200", [("MY_TEMP", REJECTED)]),
                                          ("warm", [("MY_TEMP", REJECTED)])])
def test_a_userdef_range_from_the_header(ref, value, expect):
    assert findings_for(ref, {"MY_TEMP": value}, field("USERDEF1", "MY_TEMP,{-50:150}", "N")) == expect


def test_a_deleted_value_is_a_warning_not_a_rejection(ref):
    e = ref("3.1.7").enums["dxcc_entity_code"]
    deleted = next(code for code, rows in e.index.items() if all(r["deleted"] for r in rows))
    assert findings_for(ref, {"DXCC": deleted}) == [("DXCC", WARNING)]
