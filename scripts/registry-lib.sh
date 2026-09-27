#!/usr/bin/env bash
# registry-lib.sh — sourced by publish.sh and verify-pull.sh. Picks the container engine, logs in
# to docker.io with the token from Vault through a temporary auth file (deleted on exit), and
# provides hub() for Docker Hub's API. The token never reaches argv or a lasting config.
NAMESPACE=ki7mt
ACCOUNT=ki7mt
if command -v podman >/dev/null; then ENGINE=podman; elif command -v docker >/dev/null; then ENGINE=docker
else echo "registry: need podman or docker" >&2; exit 1; fi

REG_TMP="$(mktemp -d)"; chmod 700 "$REG_TMP"
trap 'rm -rf "$REG_TMP"' EXIT
_token="$(vault-secret dockerhub/account/ki7mt)" \
  || { echo "registry: cannot read secret/dockerhub/account/ki7mt from Vault" >&2; exit 1; }
if [ "$ENGINE" = podman ]; then
  export REGISTRY_AUTH_FILE="$REG_TMP/auth.json"
  printf '%s' "$_token" | podman login --authfile "$REGISTRY_AUTH_FILE" -u "$ACCOUNT" --password-stdin docker.io >/dev/null
else
  export DOCKER_CONFIG="$REG_TMP"
  printf '%s' "$_token" | docker login -u "$ACCOUNT" --password-stdin >/dev/null 2>&1
fi
HUB_JWT="$(printf '{"username":"%s","password":"%s"}' "$ACCOUNT" "$_token" \
  | curl -sf -H 'Content-Type: application/json' --data @- https://hub.docker.com/v2/users/login | jq -r .token)"
unset _token
hub() { curl -sS -K <(printf 'header = "Authorization: Bearer %s"\n' "$HUB_JWT") "$@"; }
