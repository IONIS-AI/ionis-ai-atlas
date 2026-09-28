"""The browser boundary (Atlas SPEC.md, "Security"). Needs no database: these routes never query it,
and the client is not entered as a context manager, so the connection pool is never opened."""
import re

import pytest
from fastapi.testclient import TestClient

from atlas_api.main import app

ROUTES = ["/api/docs", "/api/docs/init.js", "/api/v1/openapi.json"]

# THE CONTRACT, written out here and never imported from the code under test (#59): an oracle taken
# from main.SECURITY_HEADERS moves with the code, so deleting a header there deleted it from the test
# too, and every test still passed. BUILD-SPEC "The browser boundary" requires a strict CSP allowing
# only Atlas's own origin, X-Content-Type-Options: nosniff, frame-ancestors 'none' and a
# Referrer-Policy; the rest are the defence in depth Atlas promises alongside them.
REQUIRED = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
CSP_REQUIRED = {"default-src": "'self'", "script-src": "'self'", "object-src": "'none'",
                "base-uri": "'none'", "frame-ancestors": "'none'"}


def assert_boundary_headers(r):
    for name, value in REQUIRED.items():
        assert r.headers.get(name) == value, f"{name} on {r.request.url} (HTTP {r.status_code})"
    csp = dict(d.strip().split(" ", 1) for d in r.headers.get("Content-Security-Policy", "").split(";") if d.strip())
    for directive, value in CSP_REQUIRED.items():
        assert csp.get(directive) == value, f"CSP {directive} on {r.request.url} (HTTP {r.status_code})"


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
    assert_boundary_headers(r)


@pytest.mark.parametrize("path, status", [
    ("/api/v1/no-such-route", 404),                  # not found
    ("/api/v1/adif/bands?limit=-1", 422),            # refused by validation, before any database call
])
def test_security_headers_on_errors(local, path, status):
    r = local.get(path)
    assert r.status_code == status
    assert_boundary_headers(r)


def test_security_headers_on_refusals():
    r = TestClient(app, base_url="http://evil.example").get("/api/docs")
    assert r.status_code == 400
    assert_boundary_headers(r)


def test_csp_allows_no_inline_or_remote_script(local):
    """Read from the response the browser gets, not from the code that builds it."""
    csp = dict(d.strip().split(" ", 1) for d in local.get("/api/docs").headers["Content-Security-Policy"].split(";"))
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


def test_head_on_pages_is_not_405(local):
    """A proxy or uptime check probes with HEAD; the page route must answer it like GET."""
    assert local.head("/").status_code == local.get("/").status_code != 405
