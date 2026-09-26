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
