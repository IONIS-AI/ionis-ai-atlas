"""The release a running Atlas reports (ionis-ai-atlas#30). Needs no database.

The version reaches the app through the environment (Containerfile ARG -> ENV, passed by publish.sh),
and is read once at import. Each case therefore imports the app in a fresh interpreter with the
environment set the way the image sets it, rather than patching a module that is already loaded.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]

PROBE = """
import json
from fastapi.testclient import TestClient
from atlas_api.main import app
# localhost: Atlas refuses any other Host (DNS-rebinding guard). No `with`: the database pool never starts.
c = TestClient(app, base_url="http://localhost")
print(json.dumps({"endpoint": c.get("/api/v1/version").json(),
                  "openapi": c.get("/api/v1/openapi.json").json()["info"]["version"]}))
"""


def probe(**env):
    clean = {k: v for k, v in os.environ.items() if k not in ("ATLAS_VERSION", "ATLAS_REVISION")}
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=API_DIR, env={**clean, **env},
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_a_build_without_a_version_says_dev_never_a_release():
    r = probe()
    assert r["endpoint"] == {"version": "dev", "revision": "unknown"}
    assert r["openapi"] == "dev"            # no hard-coded "1.0.0" to mislead anyone


def test_a_published_build_reports_its_release_everywhere():
    r = probe(ATLAS_VERSION="0.1.3", ATLAS_REVISION="0123456789abcdef0123456789abcdef01234567")
    assert r["endpoint"] == {"version": "0.1.3", "revision": "0123456789abcdef0123456789abcdef01234567"}
    assert r["openapi"] == "0.1.3"          # Swagger's title line shows the same release


def test_an_empty_build_arg_is_not_an_empty_version():
    assert probe(ATLAS_VERSION="", ATLAS_REVISION="")["endpoint"] == {"version": "dev", "revision": "unknown"}
