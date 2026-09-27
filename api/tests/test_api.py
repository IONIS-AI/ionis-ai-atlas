"""Integration tests against a real Atlas database image.

Run with the database image up, e.g.:
    podman run -d --name atlas-db-test -p 55433:5432 localhost/ionis-ai-atlas-db:dev
    ATLAS_DB_URL=postgresql://atlas_ro:atlas@127.0.0.1:55433/ionis pytest api/tests
"""
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from adif_files import engine_current, published, records

DB = os.environ.get("ATLAS_DB_URL")
pytestmark = pytest.mark.skipif(not DB, reason="ATLAS_DB_URL not set: needs a running Atlas database image")


@pytest.fixture(scope="module")
def client():
    from atlas_api.main import app

    with TestClient(app, base_url="http://localhost") as c:  # the Host allowlist refuses "testserver"
        yield c


# SPEC R17: the same tests hold for whichever ADIF version the engine carries. No count and no version
# is written here; each comes from ADIF's own all.json for the version under test (adif_files.py).
NOW = engine_current()
COUNTED = [("/api/v1/adif/bands", "Band"), ("/api/v1/adif/modes", "Mode"),
           ("/api/v1/adif/dxcc", "DXCC_Entity_Code"), ("/api/v1/adif/contests", "Contest_ID")]


@pytest.mark.parametrize("path,enumeration", COUNTED)
def test_current_version_counts(client, path, enumeration):
    r = client.get(path)
    assert r.status_code == 200 and len(r.json()) == records(NOW, enumeration)


def test_fields_and_datatypes_count_as_published(client):
    adif = published(NOW)
    assert len(client.get("/api/v1/adif/fields").json()) == len(adif["Fields"]["Records"])
    assert len(client.get("/api/v1/adif/datatypes").json()) == len(adif["DataTypes"]["Records"])


def test_current_is_the_engines_configured_version(client):
    assert client.get("/api/v1/adif/current").json()["adif_version"] == NOW


def test_every_loaded_version_serves_its_own_counts(client):
    """Versions coexist: each answers with its own published numbers, not the current one's."""
    for rel in client.get("/api/v1/adif/releases").json():
        v = rel["adif_version"]
        assert len(client.get("/api/v1/adif/modes", params={"adif_version": v}).json()) == records(v, "Mode"), v


def test_unknown_version_is_404(client):
    assert client.get("/api/v1/adif/bands", params={"adif_version": "9.9.9"}).status_code == 404


def test_ft4_is_a_submode_of_mfsk(client):
    mfsk = [m for m in client.get("/api/v1/adif/modes").json() if m["mode"] == "MFSK"][0]
    assert "FT4" in mfsk["submodes"]


def test_frequencies_are_numbers(client):
    b20 = [b for b in client.get("/api/v1/adif/bands").json() if b["band"] == "20m"][0]
    assert (b20["lower_freq_mhz"], b20["upper_freq_mhz"]) == (14.0, 14.35)


def test_openapi_is_versioned_and_swagger_is_local(client):
    assert client.get("/api/v1/openapi.json").json()["info"]["title"] == "IONIS-AI Atlas API"
    html = client.get("/api/docs").text
    assert "/static/swagger/swagger-ui-bundle.js" in html and "cdn" not in html.lower()


def test_redoc_is_off(client):
    assert client.get("/redoc").status_code != 200 or "redoc" not in client.get("/redoc").text.lower()


def test_the_api_role_cannot_write():
    """R12: proved against the database, not by reading the grants."""
    with psycopg.connect(DB) as conn:
        with pytest.raises(psycopg.errors.Error):
            conn.execute("INSERT INTO adif.release VALUES ('x','x',NULL,NULL,'x','x')")


def test_every_published_enumeration_is_listed_with_adifs_total(client):
    e = client.get("/api/v1/adif/enumerations").json()
    published_enums = published(NOW)["Enumerations"]
    assert {x["name"] for x in e} == set(published_enums)
    assert sum(x["records"] for x in e) == sum(len(p["Records"]) for p in published_enums.values())
    assert "Country" not in {x["name"] for x in e}


def test_every_enumeration_is_readable_and_complete(client):
    for x in client.get("/api/v1/adif/enumerations").json():
        body = client.get(f"/api/v1/adif/enumerations/{x['name']}").json()
        assert len(body["rows"]) == x["records"], x["name"]
        assert {"adif_version", "record"}.isdisjoint(c["name"] for c in body["columns"])


def test_unknown_or_hostile_enumeration_name_is_404(client):
    for bad in ("nosuch", "release", "field", 'band; DROP TABLE adif.band', "..%2Fcurrent", "band%00"):
        assert client.get(f"/api/v1/adif/enumerations/{bad}").status_code == 404, bad


# --- R15: lists paged and filtered on the server ----------------------------------------------
PAS = "/api/v1/adif/enumerations/primary_administrative_subdivision"
PAS_N = records(NOW, "Primary_Administrative_Subdivision")


def test_a_page_says_how_many_rows_there_are_in_all(client):
    r = client.get(PAS, params={"limit": 100})
    body = r.json()
    assert len(body["rows"]) == 100 and body["total"] == PAS_N and body["limit"] == 100 and body["offset"] == 0
    assert r.headers["X-Total-Count"] == str(PAS_N)
    assert 'rel="next"' in r.headers["Link"] and "offset=100" in r.headers["Link"]


def test_walking_the_pages_returns_every_row_once(client):
    """Pages must neither overlap nor skip: the order is unique, and the walk reassembles the table."""
    whole = client.get(PAS).json()["rows"]
    walked, offset = [], 0
    while True:
        page = client.get(PAS, params={"limit": 300, "offset": offset})
        walked += page.json()["rows"]
        if "Link" not in page.headers:
            break
        offset += 300
    assert len(walked) == len(whole) == PAS_N
    assert walked == whole
    assert len({r["record_key"] for r in walked}) == PAS_N


def test_the_last_page_has_no_next_link(client):
    last = (PAS_N - 1) // 100 * 100
    r = client.get(PAS, params={"limit": 100, "offset": last})
    assert len(r.json()["rows"]) == PAS_N - last and "Link" not in r.headers


def test_search_runs_before_paging_so_the_total_is_of_matches(client):
    r = client.get("/api/v1/adif/enumerations/dxcc_entity_code", params={"q": "bouvet", "limit": 10})
    names = [x["entity_name"] for x in r.json()["rows"]]
    assert r.json()["total"] == len(names) >= 1 and all("BOUVET" in n.upper() for n in names)


def test_search_wildcards_are_literal(client):
    # % and _ must not act as ILIKE wildcards: "%" alone would otherwise match every row.
    assert client.get("/api/v1/adif/enumerations/dxcc_entity_code", params={"q": "%"}).json()["total"] == 0


def test_a_mode_search_finds_it_by_its_submode(client):
    r = client.get("/api/v1/adif/modes", params={"q": "ft4"})
    assert [m["mode"] for m in r.json()] == ["MFSK"] and r.headers["X-Total-Count"] == "1"


def test_filter_on_a_column_exactly(client):
    r = client.get(PAS, params={"dxcc_entity_code": "15", "limit": 1000}).json()
    assert r["total"] == len(r["rows"]) > 0 and {x["dxcc_entity_code"] for x in r["rows"]} == {15}


def test_filter_on_a_column_the_enumeration_does_not_have_is_refused(client):
    r = client.get(PAS, params={"no_such_column": "1"})
    assert r.status_code == 400 and "no column 'no_such_column'" in r.json()["detail"]


def test_limit_is_capped(client):
    assert client.get(PAS, params={"limit": 1001}).status_code == 422
    assert client.get(PAS, params={"limit": 0}).status_code == 422


@pytest.mark.parametrize("path,count", [(p, lambda e=e: records(NOW, e)) for p, e in COUNTED] + [
    ("/api/v1/adif/fields", lambda: len(published(NOW)["Fields"]["Records"])),
    ("/api/v1/adif/datatypes", lambda: len(published(NOW)["DataTypes"]["Records"])),
])
def test_without_limit_arrays_return_everything_as_before(client, path, count):
    """The contract is additive: a pre-R15 caller gets the whole list, and now a count header too."""
    count = count()
    r = client.get(path)
    assert len(r.json()) == count and r.headers["X-Total-Count"] == str(count) and "Link" not in r.headers


def test_array_endpoints_page_too(client):
    n = len(published(NOW)["Fields"]["Records"])
    offset = n - 36                                     # the short last page
    r = client.get("/api/v1/adif/fields", params={"limit": 50, "offset": offset})
    assert len(r.json()) == 36 and r.headers["X-Total-Count"] == str(n) and "Link" not in r.headers


# --- R16: one name per thing, from the spec ----------------------------------------------------
def test_the_canonical_route_is_the_table_name_and_names_its_file(client):
    r = client.get("/api/v1/adif/enumerations/secondary_administrative_subdivision").json()
    assert r["name"] == "Secondary_Administrative_Subdivision"
    assert r["table"] == "secondary_administrative_subdivision"
    assert r["file"] == "enumerations_secondary_administrative_subdivision.json"
    assert r["total"] == records(NOW, "Secondary_Administrative_Subdivision")


@pytest.mark.parametrize("spelling", ["Secondary_Administrative_Subdivision", "SECONDARY_ADMINISTRATIVE_SUBDIVISION",
                                      "Secondary_administrative_subdivision"])
def test_adifs_own_spelling_is_accepted_in_any_case(client, spelling):
    assert client.get(f"/api/v1/adif/enumerations/{spelling}").json()["table"] == "secondary_administrative_subdivision"


def test_the_summary_lists_route_segment_and_file_for_every_enumeration(client):
    for e in client.get("/api/v1/adif/enumerations").json():
        assert e["file"] == f"enumerations_{e['table']}.json" and e["table"] == e["name"].lower()


# --- R17: curated views degrade, never break ---------------------------------------------------
@pytest.fixture
def dropped(monkeypatch):
    """Pretend a later ADIF version dropped columns from a table: present() stops reporting them."""
    import atlas_api.main as m
    real = m.present

    def drop(table, *cols):
        monkeypatch.setattr(m, "present", lambda t: real(t) - (set(cols) if t == table else set()))
    return drop


def test_bands_survive_losing_their_frequencies(client, dropped):
    dropped("band", "lower_freq_mhz", "upper_freq_mhz")
    whole = client.get("/api/v1/adif/bands")
    assert whole.status_code == 200 and len(whole.json()) == records(NOW, "Band")
    assert all(b["lower_freq_mhz"] is None and b["upper_freq_mhz"] is None for b in whole.json())
    # With every frequency NULL the band name breaks the tie, so pages still neither overlap nor skip.
    paged = client.get("/api/v1/adif/bands", params={"limit": 10}).json() + \
        client.get("/api/v1/adif/bands", params={"limit": 10, "offset": 10}).json()
    assert paged == whole.json()[:20]


def test_dxcc_survives_losing_entity_names(client, dropped):
    dropped("dxcc_entity_code", "entity_name")
    r = client.get("/api/v1/adif/dxcc")
    assert r.status_code == 200 and {e["entity_name"] for e in r.json()} == {""}


def test_modes_survive_losing_descriptions_and_keep_submodes(client, dropped):
    # Over EVERY row, not one: most modes have no description in ADIF (MFSK among them), so a single
    # row can't tell the fallback from the real value. A few do carry one, so this fails if the
    # dropped column is still being read (Watson, #49).
    assert any(m["description"] for m in client.get("/api/v1/adif/modes").json()), "no mode has a description to lose"
    dropped("mode", "description")
    r = client.get("/api/v1/adif/modes")
    mfsk = next(m for m in r.json() if m["mode"] == "MFSK")
    assert r.status_code == 200 and {m["description"] for m in r.json()} == {None} and "FT4" in mfsk["submodes"]


@pytest.mark.parametrize("path,table", [("/api/v1/adif/contests", "contest_id"), ("/api/v1/adif/fields", "field"),
                                        ("/api/v1/adif/datatypes", "datatype")])
def test_a_dropped_flag_reads_false(client, dropped, path, table):
    dropped(table, "import_only")
    r = client.get(path)
    assert r.status_code == 200 and {x["import_only"] for x in r.json()} == {False}


def test_flags_that_are_present_still_read_true_where_adif_sets_them(client):
    """The coalesce must not flatten real values: ADIF marks some bands import-only."""
    assert any(b["import_only"] for b in client.get("/api/v1/adif/bands").json()) or \
        any(c["import_only"] for c in client.get("/api/v1/adif/contests").json())


# --- #38: the filters each view offers --------------------------------------------------------
def test_which_band_contains_a_frequency(client):
    r = client.get("/api/v1/adif/bands", params={"freq_mhz": 14.074})
    assert [b["band"] for b in r.json()] == ["20m"] and r.headers["X-Total-Count"] == "1"
    edge = client.get("/api/v1/adif/bands", params={"freq_mhz": 14.35}).json()        # bounds are inclusive
    assert [b["band"] for b in edge] == ["20m"]
    assert client.get("/api/v1/adif/bands", params={"freq_mhz": 0.001}).json() == []  # below every band


def test_fields_by_data_type(client):
    want = sum(1 for f in published(NOW)["Fields"]["Records"].values() if f.get("Data Type") == "Enumeration")
    r = client.get("/api/v1/adif/fields", params={"data_type": "Enumeration", "limit": 1000})
    assert want > 0 and len(r.json()) == want and {f["data_type"] for f in r.json()} == {"Enumeration"}


def test_the_distinct_values_of_a_column_add_up_to_the_table(client):
    vals = client.get(f"{PAS}/values/dxcc_entity_code").json()
    recs = published(NOW)["Enumerations"]["Primary_Administrative_Subdivision"]["Records"].values()
    assert sum(v["count"] for v in vals) == PAS_N
    assert {v["value"] for v in vals} == {r["DXCC Entity Code"] for r in recs}
    first = vals[0]
    assert client.get(PAS, params={"dxcc_entity_code": first["value"]}).json()["total"] == first["count"]


def test_distinct_values_of_a_flag_include_empty(client):
    vals = {v["value"]: v["count"] for v in client.get("/api/v1/adif/enumerations/dxcc_entity_code/values/deleted").json()}
    assert sum(vals.values()) == records(NOW, "DXCC_Entity_Code") and "true" in vals


@pytest.mark.parametrize("column", ["no_such_column", "record_key", "adif_version", "record"])
def test_distinct_values_of_an_unknown_column_is_404(client, column):
    assert client.get(f"{PAS}/values/{column}").status_code == 404


def test_a_flag_filter_reads_an_empty_flag_as_false(client):
    """ADIF leaves `Deleted` empty on live entities; "not deleted" must find them, not nothing."""
    recs = published(NOW)["Enumerations"]["DXCC_Entity_Code"]["Records"].values()
    deleted = sum(1 for r in recs if r.get("Deleted") == "true")
    d = "/api/v1/adif/enumerations/dxcc_entity_code"
    assert client.get(d, params={"deleted": "true"}).json()["total"] == deleted > 0
    assert client.get(d, params={"deleted": "false"}).json()["total"] == len(recs) - deleted
    assert client.get(d, params={"deleted": "FALSE"}).json()["total"] == len(recs) - deleted
