"""ADIF's published files, for tests that must hold for WHICHEVER ADIF version an engine carries.

SPEC R17: a new ADIF version is data, not code, proved by running the same tests on an engine
carrying 3.1.6 alone and on one carrying 3.1.7. So no test states "33 bands" or "3.1.7": the expected
numbers come from ADIF's own all.json for the version under test, and the expected current version
from the engine's configuration (db/load/atlas-db-lib.sh, or ATLAS_ADIF_CURRENT as the image sets it).

ADIF's resource zips come from adif.org, verified against the pin the database image was built from,
and cached (ATLAS_ADIF_CACHE, default ~/.cache/ionis-ai-atlas/adif). A zip that does not match the
pin FAILS; only an unreachable adif.org with nothing cached skips.
"""
import functools
import hashlib
import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path

import pytest

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


@functools.lru_cache(maxsize=None)
def published(version: str) -> dict:
    """ADIF's all.json for `version`: the "Adif" object, as ADIF published it."""
    z = resource_zip(version)
    raw = z.read(next(n for n in z.namelist() if n.endswith("exports/json/all.json")))
    return json.loads(raw.decode("utf-8-sig"))["Adif"]


def records(version: str, enumeration: str) -> int:
    return len(published(version)["Enumerations"][enumeration]["Records"])


def engine_current() -> str:
    """The ADIF version the engine points the database at: ATLAS_ADIF_CURRENT when the image was
    built with one (the rehearsal), otherwise the release's line in atlas-db-lib.sh."""
    lib = (ROOT / "db/load/atlas-db-lib.sh").read_text()
    return os.environ.get("ATLAS_ADIF_CURRENT") or re.search(r"^ADIF_CURRENT=([0-9.]+)", lib, re.M).group(1)
