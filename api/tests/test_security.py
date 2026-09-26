"""The browser boundary (Atlas SPEC.md, "Security"). Needs no database: these routes never query it,
and the client is not entered as a context manager, so the connection pool is never opened."""
import re

import pytest
from fastapi.testclient import TestClient

from atlas_api.main import SECURITY_HEADERS, app

ROUTES = ["/api/docs", "/api/docs/init.js", "/api/v1/openapi.json"]


@pytest.fixture(scope="module")
def local():
    return TestClient(app, base_url="http://localhost")


@pytest.mark.parametrize("host", ["localhost", "localhost:8080", "127.0.0.1", "127.0.0.1:8080"])
def test_local_hosts_answered(host):
    assert TestClient(app, base_url=f"http://{host}").get("/api/v1/openapi.json").status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8080", "192.168.1.50", "localhost.evil.example"])
def test_foreign_host_refused(host):
    """DNS rebinding: a hostile page re-points its own name at 127.0.0.1, but keeps its Host header."""
    r = TestClient(app, base_url=f"http://{host}").get("/api/v1/openapi.json")
    assert r.status_code == 400
    assert "openapi" not in r.text


@pytest.mark.parametrize("path", ROUTES)
def test_security_headers_on_every_response(local, path):
    r = local.get(path)
    assert r.status_code == 200
    for name, value in SECURITY_HEADERS.items():
        assert r.headers.get(name) == value, name


def test_security_headers_on_refusals():
    r = TestClient(app, base_url="http://evil.example").get("/api/docs")
    for name, value in SECURITY_HEADERS.items():
        assert r.headers.get(name) == value, name


def test_csp_allows_no_inline_or_remote_script():
    csp = dict(d.split(" ", 1) for d in SECURITY_HEADERS["Content-Security-Policy"].split("; "))
    assert csp["script-src"] == "'self'"
    assert csp["default-src"] == "'self'"
    assert csp["frame-ancestors"] == "'none'"


def test_docs_page_has_no_inline_script(local):
    """The CSP refuses inline scripts, so the Swagger page must not need one."""
    html = local.get("/api/docs").text
    for tag in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S):
        assert tag.strip() == "", "inline script in /api/docs"
    assert '<script src="/api/docs/init.js">' in html


def test_no_cors(local):
    r = local.get("/api/v1/openapi.json", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
