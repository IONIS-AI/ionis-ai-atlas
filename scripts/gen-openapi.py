#!/usr/bin/env python3
"""Write the API's OpenAPI description to api/openapi.json (the published /api/v1 contract).

Committed, so every contract change shows up in review as a diff. The web client is generated
from this file (npm run gen:api), so the front end cannot drift from the API."""
import json, os, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "api"))
os.environ.setdefault("ATLAS_STATIC", "/nonexistent")
from atlas_api.main import app  # noqa: E402
(root / "api" / "openapi.json").write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print("api/openapi.json written")
