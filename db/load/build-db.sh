#!/usr/bin/env bash
# build-db.sh — runs INSIDE the database image build: fetch and verify ADIF, then build and prove a
# cluster from it.
#
# The verified ADIF files stay in the image ($SPEC), outside the data directory, because every
# container start re-applies them (entrypoint.sh). The cluster built here is what a new install
# starts from, so a first start performs no load; the build fails if its audit does, so an image
# that builds is an image whose reference data was verified.
set -euo pipefail
. /opt/atlas-load/atlas-db-lib.sh

# 1. ADIF's own files, from adif.org, verified against the pinned SHA-256 of each resource zip.
python3 - "$PINS" "$SPEC" <<'PY'
import hashlib, io, json, os, sys, urllib.request, zipfile
pins, spec = json.load(open(sys.argv[1])), sys.argv[2]
for vdir, v in pins["versions"].items():
    raw = urllib.request.urlopen(v["source"], timeout=120).read()
    got = hashlib.sha256(raw).hexdigest()
    if got != v["zip_sha256"]:
        sys.exit(f"{v['source']}: SHA-256 {got} is not the pinned {v['zip_sha256']}")
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in z.namelist() if n.endswith("exports/json/all.json"))
    os.makedirs(f"{spec}/{vdir}", exist_ok=True)
    open(f"{spec}/{vdir}/all.json", "wb").write(z.read(name))
    print(f"ADIF {vdir}: zip verified, all.json extracted")
PY

# 2. The cluster, the reference data, the proof.
init_cluster
start_private
apply_reference
audit_reference
psql -d ionis -c "VACUUM ANALYZE"
stop_private
