#!/usr/bin/env bash
# rehearse-adif-version.sh — prove a new ADIF version drops in with no code change (SPEC R17, #41).
#
# "ADIF releases, we push the new version, and the UI/API continues on as before" (Judge). Rehearsed on
# the real transition we have, 3.1.6 -> 3.1.7 (3.1.7 added MODE OFDM and four submodes):
#
#   1. OLD      an engine carrying 3.1.6 ONLY, fresh volume: the API and UI suites pass.
#   2. UPGRADE  the release engine (3.1.6 + 3.1.7, current 3.1.7) on THAT volume, as a user's
#               `docker compose pull && docker compose up` would: the same suites, unchanged, pass,
#               and OFDM is now served where it was not.
#   3. FRESH    the release engine on a new volume: the same suites pass.
#
# Between the steps only the engine image changes: the same app image, the same tests. The tests take
# every ADIF count from ADIF's own all.json for the version under test (api/tests/adif_files.py), and
# check-ui takes its totals from the API, so nothing in them names 3.1.6 or 3.1.7.
#
# Needs docker or podman (ENGINE: $ENGINE, else docker if installed, else podman), the API test
# requirements for PY, and uv (or playwright) for check-ui.
#   make rehearse-adif
set -euo pipefail
cd "$(dirname "$0")/.."

ENGINE="${ENGINE:-$(command -v docker >/dev/null && echo docker || echo podman)}"
PY="${PY:-python3.12}"
P=atlas-rehearse
NET="$P" VOL="$P-pgdata" FRESH_VOL="$P-pgdata-fresh"
DBPORT=55440 APPPORT=18440
OLD=localhost/ionis-ai-atlas-db:rehearse-3.1.6
NEW=localhost/ionis-ai-atlas-db:rehearse-release
APP=localhost/ionis-ai-atlas:rehearse
# podman ignores HEALTHCHECK in OCI-format images unless built as docker format (as `make images`).
FMT=(); [ "$ENGINE" = podman ] && FMT=(--format docker)

say() { printf '\n=== %s\n' "$*"; }
stop() { "$ENGINE" rm -f "$P-db" "$P-app" >/dev/null 2>&1 || true; }
cleanup() {
  stop
  "$ENGINE" volume rm -f "$VOL" "$FRESH_VOL" >/dev/null 2>&1 || true
  "$ENGINE" network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

say "build: an engine carrying 3.1.6 only, the release engine, and the app ($ENGINE)"
"$ENGINE" build -q "${FMT[@]}" --build-arg ATLAS_ADIF_VERSIONS=3.1.6 --build-arg ATLAS_ADIF_CURRENT=3.1.6 \
  -t "$OLD" -f db/Containerfile db >/dev/null
"$ENGINE" build -q "${FMT[@]}" -t "$NEW" -f db/Containerfile db >/dev/null
"$ENGINE" build -q "${FMT[@]}" -t "$APP" -f Containerfile . >/dev/null
"$ENGINE" network create "$NET" >/dev/null

start() {   # start <db image> <volume>
  "$ENGINE" run -d --name "$P-db" --network "$NET" --network-alias db -v "$2:/var/lib/pgsql/17/data" \
    -p "127.0.0.1:$DBPORT:5432" "$1" >/dev/null
  for _ in $(seq 180); do
    "$ENGINE" exec "$P-db" pg_isready -q -h 127.0.0.1 -d ionis -U atlas_ro 2>/dev/null && break; sleep 1
  done
  "$ENGINE" run -d --name "$P-app" --network "$NET" -p "127.0.0.1:$APPPORT:8080" --read-only --tmpfs /tmp \
    --cap-drop ALL -e ATLAS_DB_URL=postgresql://atlas_ro:atlas@db:5432/ionis "$APP" >/dev/null
  for _ in $(seq 60); do curl -sf "http://127.0.0.1:$APPPORT/api/v1/health" >/dev/null && return; sleep 1; done
  echo "rehearse: the stack did not come up"; "$ENGINE" logs "$P-db" | tail -20; exit 1
}

suites() {   # suites <expected current ADIF version>
  local current; current="$(curl -s "http://127.0.0.1:$APPPORT/api/v1/adif/current" | "$PY" -c 'import json,sys;print(json.load(sys.stdin)["adif_version"])')"
  [ "$current" = "$1" ] || { echo "rehearse: engine serves ADIF $current, expected $1"; exit 1; }
  echo "serving ADIF $current"
  (cd api && ATLAS_ADIF_CURRENT="$1" ATLAS_DB_URL="postgresql://atlas_ro:atlas@127.0.0.1:$DBPORT/ionis" \
     ATLAS_STATIC=/nonexistent "$PY" -m pytest -q -p no:warnings tests | tail -1)
  make -s check-ui BASE="http://localhost:$APPPORT" | tail -1
}

ofdm() { curl -s "http://127.0.0.1:$APPPORT/api/v1/adif/modes?q=OFDM" -D - -o /dev/null | tr -d '\r' | awk -F': ' 'tolower($1)=="x-total-count"{print $2}'; }

say "1. OLD: an engine carrying 3.1.6 only, fresh volume"
start "$OLD" "$VOL"
suites 3.1.6
[ "$(ofdm)" = 0 ] || { echo "rehearse: OFDM served under 3.1.6"; exit 1; }
echo "OFDM: not served (3.1.6 has no such mode)"
stop

say "2. UPGRADE: the release engine on the SAME volume"
start "$NEW" "$VOL"
suites 3.1.7
[ "$(ofdm)" = 1 ] || { echo "rehearse: OFDM not served after the upgrade"; exit 1; }
echo "OFDM: served, with no code change"
stop

say "3. FRESH: the release engine on a new volume"
start "$NEW" "$FRESH_VOL"
suites 3.1.7

say "rehearse: PASS. 3.1.6 -> 3.1.7 dropped in with no change to api/, web/ or the tests"
