#!/usr/bin/env bash
# entrypoint.sh — reconcile the database volume with this engine image, then run PostgreSQL.
# Runs on every start. See atlas-db-lib.sh for why: the volume is a cache, never trusted to hold
# what the current image carries.
set -Eeuo pipefail
. /opt/atlas-load/atlas-db-lib.sh
# Any failure below stops the start: Atlas never serves a database that did not reconcile. (Kept as
# plain calls, not an `if`, because bash suspends `set -e` inside an if-condition.)
trap 'echo "atlas-db: reference data failed to reconcile; refusing to serve" >&2' ERR

# A data directory from another PostgreSQL major cannot be opened. Everything in it can be rebuilt
# from the images, so rebuild rather than attempt an in-place upgrade.
if [ -s "$PGDATA/PG_VERSION" ] && [ "$(cat "$PGDATA/PG_VERSION")" != "$PG_MAJOR" ]; then
  echo "atlas-db: data directory is PostgreSQL $(cat "$PGDATA/PG_VERSION"), this engine is $PG_MAJOR; rebuilding it from the images"
  find "$PGDATA" -mindepth 1 -delete
fi
[ -s "$PGDATA/PG_VERSION" ] || init_cluster

start_private
apply_reference
audit_reference
stop_private
echo "atlas-db: reconciled; starting PostgreSQL"
exec "$PGBIN/postgres" -D "$PGDATA"
