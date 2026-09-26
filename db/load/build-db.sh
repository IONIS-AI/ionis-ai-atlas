#!/usr/bin/env bash
# build-db.sh — runs INSIDE the database image build: create the cluster, load ADIF, prove it, stop.
#
# The image ships initialised, so a user's first `docker compose up` performs no load. Every step
# that can be checked is checked here, and a failed check fails the image build: an image that
# builds is an image whose data was audited.
set -euo pipefail

PGBIN=/usr/pgsql-17/bin
LOAD=/opt/atlas-load
SPEC=/tmp/adif-spec                      # <version dir>/all.json, the layout adif_tier.py reads
PINS="$LOAD/adif_upstream_sha256.json"

# 1. ADIF's own files, from adif.org, verified against the pinned SHA-256 of each resource zip.
python3 - "$PINS" "$SPEC" <<'EOF'
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
EOF

# 2. The cluster, tuned for the target machine (the two containers share 4 CPUs and 8 GB).
"$PGBIN/initdb" -D "$PGDATA" --auth-local=peer --auth-host=scram-sha-256 --encoding=UTF8 --locale=C.UTF-8
cat >> "$PGDATA/postgresql.conf" <<'EOF'
# --- IONIS Atlas: tuned for the target machine (Atlas SPEC.md, "Target machine") ---
listen_addresses = '*'
max_connections = 30
shared_buffers = 1GB
effective_cache_size = 3GB
work_mem = 32MB
maintenance_work_mem = 256MB
jit = off
EOF
cat >> "$PGDATA/pg_hba.conf" <<'EOF'
# --- IONIS Atlas: only the read-only role, over the compose network ---
host  ionis  atlas_ro  0.0.0.0/0  scram-sha-256
host  ionis  atlas_ro  ::/0       scram-sha-256
EOF
"$PGBIN/pg_ctl" -D "$PGDATA" -o "-c listen_addresses=''" -w start
psql() { "$PGBIN/psql" -X -v ON_ERROR_STOP=1 -q "$@"; }

# 3. The database and its read-only role. atlas_ro's password is NOT a secret: the role reads
#    published reference data and nothing else, and the port is not published outside compose.
psql -d postgres <<'EOF'
CREATE DATABASE ionis;
CREATE ROLE atlas_ro LOGIN PASSWORD 'atlas' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE atlas_ro SET default_transaction_read_only = on;
ALTER ROLE atlas_ro SET statement_timeout = '15s';
EOF
psql -d ionis -c "CREATE EXTENSION IF NOT EXISTS vector"

# 4. ADIF: schema, both versions (each one transaction), the current pointer.
psql -d ionis -f "$LOAD/10-adif_schema.sql"
for v in 3.1.6 3.1.7; do
  python3 "$LOAD/adif_tier.py" load --spec-dir "$SPEC" --pins "$PINS" --version "$v" | psql -d ionis -1
done
python3 "$LOAD/adif_tier.py" set-current --spec-dir "$SPEC" --pins "$PINS" --version 3.1.7 | psql -d ionis

# 5. Grants for the read-only role, now and for anything created later.
psql -d ionis <<'EOF'
GRANT CONNECT ON DATABASE ionis TO atlas_ro;
GRANT USAGE ON SCHEMA adif TO atlas_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA adif TO atlas_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA adif GRANT SELECT ON TABLES TO atlas_ro;
EOF

# 6. PROVE it: each version's counts equal ADIF's own, and atlas_ro cannot write.
for v in 3.1.6 3.1.7; do
  bad=$(python3 "$LOAD/adif_tier.py" audit --spec-dir "$SPEC" --pins "$PINS" --version "$v" | psql -d ionis -tA | grep -c . || true)
  [ "$bad" -eq 0 ] || { echo "ADIF $v audit: $bad mismatching tables"; exit 1; }
  echo "ADIF $v audit: 0 mismatches"
done
if "$PGBIN/psql" -X -q -d ionis -U postgres -c "SET ROLE atlas_ro; INSERT INTO adif.release VALUES ('x','x',NULL,NULL,'x','x')" 2>/dev/null; then
  echo "atlas_ro could write"; exit 1
fi
echo "atlas_ro write refused"

psql -d ionis -c "VACUUM ANALYZE"
"$PGBIN/pg_ctl" -D "$PGDATA" -m fast -w stop
rm -rf "$SPEC"
