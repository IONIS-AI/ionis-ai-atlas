"""Integration tests against a real Atlas database image.

Run with the database image up, e.g.:
    podman run -d --name atlas-db-test -p 55433:5432 localhost/ionis-ai-atlas-db:dev
    ATLAS_DB_URL=postgresql://atlas_ro:atlas@127.0.0.1:55433/ionis pytest api/tests
"""
import os

import psycopg
import pytest
from fastapi.testclient import TestClient

DB = os.environ.get("ATLAS_DB_URL")
pytestmark = pytest.mark.skipif(not DB, reason="ATLAS_DB_URL not set: needs a running Atlas database image")


@pytest.fixture(scope="module")
def client():
    from atlas_api.main import app

    with TestClient(app, base_url="http://localhost") as c:  # the Host allowlist refuses "testserver"
        yield c


# ADIF 3.1.7's own counts, from ADIF's published all.json.
@pytest.mark.parametrize("path,count", [
    ("/api/v1/adif/bands", 33), ("/api/v1/adif/modes", 91), ("/api/v1/adif/dxcc", 403),
    ("/api/v1/adif/contests", 256), ("/api/v1/adif/fields", 186),
])
def test_current_version_counts(client, path, count):
    r = client.get(path)
    assert r.status_code == 200 and len(r.json()) == count


def test_current_is_317(client):
    assert client.get("/api/v1/adif/current").json()["adif_version"] == "3.1.7"


def test_versions_coexist(client):
    assert len(client.get("/api/v1/adif/modes", params={"adif_version": "3.1.6"}).json()) == 90


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


def test_all_25_enumerations_are_listed_with_adif_total(client):
    e = client.get("/api/v1/adif/enumerations").json()
    assert len(e) == 25 and sum(x["records"] for x in e) == 3345
    assert "Country" not in {x["name"] for x in e}


def test_every_enumeration_is_readable_and_complete(client):
    for x in client.get("/api/v1/adif/enumerations").json():
        body = client.get(f"/api/v1/adif/enumerations/{x['name']}").json()
        assert len(body["rows"]) == x["records"], x["name"]
        assert {"adif_version", "record"}.isdisjoint(c["name"] for c in body["columns"])


def test_unknown_or_hostile_enumeration_name_is_404(client):
    for bad in ("nosuch", "release", "field", 'band; DROP TABLE adif.band', "..%2Fcurrent", "band%00"):
        assert client.get(f"/api/v1/adif/enumerations/{bad}").status_code == 404, bad


def test_datatypes(client):
    assert len(client.get("/api/v1/adif/datatypes").json()) == 28


# --- R15: lists paged and filtered on the server ----------------------------------------------
PAS = "/api/v1/adif/enumerations/primary_administrative_subdivision"


def test_a_page_says_how_many_rows_there_are_in_all(client):
    r = client.get(PAS, params={"limit": 100})
    body = r.json()
    assert len(body["rows"]) == 100 and body["total"] == 1965 and body["limit"] == 100 and body["offset"] == 0
    assert r.headers["X-Total-Count"] == "1965"
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
    assert len(walked) == len(whole) == 1965
    assert walked == whole
    assert len({r["record_key"] for r in walked}) == 1965


def test_the_last_page_has_no_next_link(client):
    r = client.get(PAS, params={"limit": 100, "offset": 1900})
    assert len(r.json()["rows"]) == 65 and "Link" not in r.headers


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


@pytest.mark.parametrize("path,count", [
    ("/api/v1/adif/bands", 33), ("/api/v1/adif/modes", 91), ("/api/v1/adif/dxcc", 403),
    ("/api/v1/adif/contests", 256), ("/api/v1/adif/fields", 186), ("/api/v1/adif/datatypes", 28),
])
def test_without_limit_arrays_return_everything_as_before(client, path, count):
    """The contract is additive: a pre-R15 caller gets the whole list, and now a count header too."""
    r = client.get(path)
    assert len(r.json()) == count and r.headers["X-Total-Count"] == str(count) and "Link" not in r.headers


def test_array_endpoints_page_too(client):
    r = client.get("/api/v1/adif/fields", params={"limit": 50, "offset": 150})
    assert len(r.json()) == 36 and r.headers["X-Total-Count"] == "186" and "Link" not in r.headers


# --- R16: one name per thing, from the spec ----------------------------------------------------
def test_the_canonical_route_is_the_table_name_and_names_its_file(client):
    r = client.get("/api/v1/adif/enumerations/secondary_administrative_subdivision").json()
    assert r["name"] == "Secondary_Administrative_Subdivision"
    assert r["table"] == "secondary_administrative_subdivision"
    assert r["file"] == "enumerations_secondary_administrative_subdivision.json"
    assert r["total"] == 58


@pytest.mark.parametrize("spelling", ["Secondary_Administrative_Subdivision", "SECONDARY_ADMINISTRATIVE_SUBDIVISION",
                                      "Secondary_administrative_subdivision"])
def test_adifs_own_spelling_is_accepted_in_any_case(client, spelling):
    assert client.get(f"/api/v1/adif/enumerations/{spelling}").json()["table"] == "secondary_administrative_subdivision"


def test_the_summary_lists_route_segment_and_file_for_every_enumeration(client):
    for e in client.get("/api/v1/adif/enumerations").json():
        assert e["file"] == f"enumerations_{e['table']}.json" and e["table"] == e["name"].lower()
