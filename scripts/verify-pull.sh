#!/usr/bin/env bash
# verify-pull.sh <sha> — prove a published release runs from docker.io alone, the way a user runs it
# (Atlas SPEC.md R9): local copies removed, images pulled, the PUBLISHED compose.yaml (database
# volume included), then checks against the running stack, a restart that exercises the volume
# reconcile, and teardown. Exit status is the verdict.
#
#   COMPOSE_EXTRA=<file>   an extra compose file, e.g. to drop CPU caps where rootless podman
#                          cannot enforce them (9975). Never needed on Docker Desktop.
#   CHANNEL=prod           verify a public release (TAG=X.Y.Z) with NO login at all, exactly as a
#                          user pulls it. dev (default) logs in, because the dev repository is private.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
SHA="${1:?usage: $0 <sha | X.Y.Z>   (what make publish printed)}"
CHANNEL="${CHANNEL:-dev}"
NAMESPACE=ki7mt
if [ "$CHANNEL" = prod ]; then
  # Anonymous on purpose: a release must install with no credential. An empty auth config replaces
  # any login this machine may hold (Docker keeps its CLI plugins linked in, as registry-lib does).
  if command -v podman >/dev/null; then ENGINE=podman; else ENGINE=docker; fi
  REG_TMP="$(mktemp -d)"; chmod 700 "$REG_TMP"
  if [ "$ENGINE" = podman ]; then
    export REGISTRY_AUTH_FILE="$REG_TMP/auth.json"; echo '{}' > "$REGISTRY_AUTH_FILE"
  else
    export DOCKER_CONFIG="$REG_TMP"
    if [ -d "$HOME/.docker/cli-plugins" ]; then ln -s "$HOME/.docker/cli-plugins" "$REG_TMP/cli-plugins"; fi
  fi
  APP="docker.io/$NAMESPACE/ionis-ai-atlas:$SHA"
  DB="docker.io/$NAMESPACE/ionis-ai-atlas-db:$SHA"
else
  . scripts/registry-lib.sh
  APP="docker.io/$NAMESPACE/ionis-ai-atlas-dev:app-$SHA"   # dev: one private repository, kind in the tag
  DB="docker.io/$NAMESPACE/ionis-ai-atlas-dev:db-$SHA"
fi
URL=http://127.0.0.1:8080
PROJECT=atlas-verify
if [ "$ENGINE" = podman ]; then COMPOSE=(podman compose); else COMPOSE=(docker compose); fi
COMPOSE+=(-p "$PROJECT" -f compose.yaml); [ -n "${COMPOSE_EXTRA:-}" ] && COMPOSE+=(-f "$COMPOSE_EXTRA")
export ATLAS_APP_IMAGE="$APP" ATLAS_DB_IMAGE="$DB"

curl -s -o /dev/null "$URL" && { echo "verify-pull: something is already on $URL; stop it first (make dev-down)" >&2; exit 1; }

fails=0
check() { if eval "$2"; then echo "  PASS  $1"; else echo "  FAIL  $1"; fails=$((fails+1)); fi; }
wait_up() { for _ in $(seq 1 90); do curl -sf "$URL/api/v1/health" >/dev/null && return 0; sleep 2; done; return 1; }
teardown() { "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true; rm -rf "$REG_TMP"; }
trap teardown EXIT

echo "verify-pull: $SHA"
$ENGINE rmi -f "$APP" "$DB" >/dev/null 2>&1 || true
# One command per line: a failure inside an `a && b` chain does not stop the script under set -e.
$ENGINE pull -q "$APP" >/dev/null
$ENGINE pull -q "$DB" >/dev/null
echo "  pulled from docker.io, no local copies used$([ "$CHANNEL" = prod ] && echo ', anonymously')"
if ! out="$("${COMPOSE[@]}" up -d 2>&1)"; then   # say why, rather than exiting silently under set -e
  echo "verify-pull: compose up failed:"; grep -v '^\s*$' <<<"$out" | tail -5 | sed 's/^/    /'; exit 1
fi

check "stack comes up healthy"               'wait_up'
check "ADIF current is 3.1.7"                '[ "$(curl -s $URL/api/v1/adif/current | jq -r .adif_version)" = 3.1.7 ]'
check "25 ADIF enumerations"                 '[ "$(curl -s $URL/api/v1/adif/enumerations | jq length)" = 25 ]'
check "front end served"                     '[ "$(curl -s -o /dev/null -w %{http_code} $URL/)" = 200 ]'
check "HEAD / answered"                      '[ "$(curl -s -I -o /dev/null -w %{http_code} $URL/)" = 200 ]'
check "Swagger UI served"                    '[ "$(curl -s -o /dev/null -w %{http_code} $URL/api/docs)" = 200 ]'
check "foreign Host refused (DNS rebinding)" '[ "$(curl -s -o /dev/null -w %{http_code} -H "Host: evil.example" $URL/api/v1/health)" = 400 ]'
check "Content-Security-Policy present"      'curl -s -D - -o /dev/null $URL/ | grep -qi "^content-security-policy: default-src .self."'
check "database on a named volume"           '"${COMPOSE[@]}" ps -q db | xargs $ENGINE inspect --format "{{range .Mounts}}{{.Type}}{{end}}" | grep -q volume'
"${COMPOSE[@]}" restart db >/dev/null 2>&1
# grep -q exits at the first match, so `compose logs | grep -q` leaves the writer with a closed
# pipe: it exits 255 and pipefail fails the whole pipeline even though the match was found. How
# often depends on how much the writer had left to flush, which is why it looked intermittent.
# Process substitution keeps the writer out of the pipeline, so only grep's status counts.
check "restart reconciles the volume"        'grep -q "ADIF 3.1.7 present" < <("${COMPOSE[@]}" logs db 2>&1) && wait_up'

echo "verify-pull: $([ $fails = 0 ] && echo PASS || echo "FAIL ($fails)")"
[ $fails = 0 ]
