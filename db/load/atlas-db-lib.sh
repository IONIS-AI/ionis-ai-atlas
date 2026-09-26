#!/usr/bin/env bash
# atlas-db-lib.sh — shared by build-db.sh (image build) and entrypoint.sh (every container start).
#
# The database volume is a cache (COLLECTION-V2-SPEC §7, Atlas SPEC "Deployment"): Docker seeds a
# named volume from the image only once, so nothing may rely on data baked into the image's data
# directory reaching an existing install. Every start therefore applies the reference data by
# version, and every function here is idempotent.

PGBIN=/usr/pgsql-17/bin
PG_MAJOR=17
LOAD=/opt/atlas-load
SPEC="$LOAD/spec"                        # ADIF's all.json per version, verified at build; not in PGDATA
PINS="$LOAD/adif_upstream_sha256.json"
ADIF_VERSIONS=(3.1.6 3.1.7)              # every ADIF version this engine image carries
ADIF_CURRENT=3.1.7                       # the version the image points the database at

psql() { PGOPTIONS='-c client_min_messages=warning' "$PGBIN/psql" -X -v ON_ERROR_STOP=1 -q "$@"; }
tier() { python3 "$LOAD/adif_tier.py" "$1" --spec-dir "$SPEC" --pins "$PINS" "${@:2}"; }

# A new cluster, tuned for the target machine (the containers share 4 CPUs and 8 GB).
init_cluster() {
  "$PGBIN/initdb" -D "$PGDATA" --auth-local=peer --auth-host=scram-sha-256 --encoding=UTF8 --locale=C.UTF-8 >/dev/null
  cat >> "$PGDATA/postgresql.conf" <<'CONF'
# --- IONIS-AI Atlas: tuned for the target machine (Atlas SPEC.md, "Target machine") ---
listen_addresses = '*'
max_connections = 30
shared_buffers = 1GB
effective_cache_size = 3GB
work_mem = 32MB
maintenance_work_mem = 256MB
jit = off
CONF
  cat >> "$PGDATA/pg_hba.conf" <<'CONF'
# --- IONIS-AI Atlas: only the read-only role, over the compose network ---
host  ionis  atlas_ro  0.0.0.0/0  scram-sha-256
host  ionis  atlas_ro  ::/0       scram-sha-256
CONF
  echo "atlas-db: new PostgreSQL $PG_MAJOR cluster initialised"
}

# Local socket only, so the TCP healthcheck fails and Atlas keeps waiting until the data is right.
start_private() { "$PGBIN/pg_ctl" -D "$PGDATA" -o "-c listen_addresses=''" -w -l /tmp/atlas-db-setup.log start >/dev/null; }
stop_private()  { "$PGBIN/pg_ctl" -D "$PGDATA" -m fast -w stop >/dev/null; }

# The database, the read-only role, and every ADIF version this image carries. Safe to repeat.
# atlas_ro's password is NOT a secret: the role reads published reference data and nothing else,
# and the database port is never published outside the compose network.
apply_reference() {
  if [ -z "$(psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'ionis'")" ]; then
    psql -d postgres -c "CREATE DATABASE ionis"
  fi
  psql -d postgres <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'atlas_ro') THEN
    CREATE ROLE atlas_ro LOGIN PASSWORD 'atlas' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;
ALTER ROLE atlas_ro SET default_transaction_read_only = on;
ALTER ROLE atlas_ro SET statement_timeout = '15s';
SQL
  psql -d ionis -c "CREATE EXTENSION IF NOT EXISTS vector"
  psql -d ionis -f "$LOAD/10-adif_schema.sql"

  # Versioned, never replaced: a version already present is left exactly as it is.
  local v
  for v in "${ADIF_VERSIONS[@]}"; do
    if [ -n "$(psql -d ionis -tAc "SELECT 1 FROM adif.release WHERE adif_version = '$v'")" ]; then
      echo "atlas-db: ADIF $v present"
    else
      tier load --version "$v" | psql -d ionis -1
      echo "atlas-db: ADIF $v added"
    fi
  done
  if [ "$(psql -d ionis -tAc "SELECT adif_version FROM adif.current")" != "$ADIF_CURRENT" ]; then
    tier set-current --version "$ADIF_CURRENT" | psql -d ionis
    echo "atlas-db: current ADIF version set to $ADIF_CURRENT"
  fi

  psql -d ionis <<'SQL'
GRANT CONNECT ON DATABASE ionis TO atlas_ro;
GRANT USAGE ON SCHEMA adif TO atlas_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA adif TO atlas_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA adif GRANT SELECT ON TABLES TO atlas_ro;
SQL
}

# PROVE it: each version's counts equal ADIF's own, and atlas_ro cannot write. Non-zero on failure.
audit_reference() {
  local v bad
  for v in "${ADIF_VERSIONS[@]}"; do
    bad=$(tier audit --version "$v" | psql -d ionis -tA | grep -c . || true)
    if [ "$bad" -ne 0 ]; then echo "atlas-db: ADIF $v audit: $bad mismatching tables"; return 1; fi
    echo "atlas-db: ADIF $v audit: 0 mismatches"
  done
  if "$PGBIN/psql" -X -q -d ionis -c "SET ROLE atlas_ro; INSERT INTO adif.release VALUES ('x','x',NULL,NULL,'x','x')" 2>/dev/null; then
    echo "atlas-db: atlas_ro could write"; return 1
  fi
  echo "atlas-db: atlas_ro write refused"
}
