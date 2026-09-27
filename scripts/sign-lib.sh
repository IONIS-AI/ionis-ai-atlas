#!/usr/bin/env bash
# sign-lib.sh — sign and verify images with cosign, keys held in Vault transit.
#
# Sourced by publish.sh (signing) and verify-pull.sh (verification). The private halves are
# non-exportable transit keys: Vault performs the ECDSA operation and returns a signature, so no
# signing key ever exists on this machine, and a stolen registry token cannot produce a signature.
#
#   ki7mt-images       releases  -> transparency log ON  (public artefacts; verifiable by anyone)
#   ki7mt-images-dev   dev       -> transparency log OFF (the repository is private: uploading
#                                  would publish its digests to a public, permanent log)
#
# Environment: DOCKER_CONFIG must already point at the registry auth written by registry-lib.sh.
# That config must be self-contained (no credsStore): cosign runs in a container and cannot execute
# a credential helper installed on the host.

# cosign v2.6.1, pinned by digest for the same reason Trivy is: a tool that signs on our behalf is
# never "whatever the tag points at today".
COSIGN_IMAGE="ghcr.io/sigstore/cosign/cosign@sha256:68839b7f13dac5a6744a5d8818e984dd39183374e37855c19e14d623d9bc9037"
CA_CERT="${CA_CERT:-$HOME/ca-roots/ki7mt-root.crt}"
SIGN_KEY_PROD=ki7mt-images
SIGN_KEY_DEV=ki7mt-images-dev

# vault_addr — the Vault address from the host AppRole. SIGNING ONLY: verification needs no Vault,
# so nothing on the verify path may call this (see cosign() below).
vault_addr() {
  local approle="${VAULT_APPROLE_FILE:-$HOME/.config/secrets/vault-approle.json}"
  [ -r "$approle" ] || { echo "sign: no AppRole at $approle" >&2; return 1; }
  python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['vault_addr'].rstrip('/'))" "$approle"
}

# vault_token_fresh — a token minted NOW from the host AppRole.
#
# Never the Vault Agent's sink token. AppRole tokens keep the policies they were ISSUED with, so a
# sink token minted before a policy was attached fails forever and reads as a missing grant rather
# than a stale token. That cost us hours on the Docker Hub secret; this function exists so the
# publish path cannot repeat it.
vault_token_fresh() {
  local approle="${VAULT_APPROLE_FILE:-$HOME/.config/secrets/vault-approle.json}"
  [ -r "$approle" ] || { echo "sign: no AppRole at $approle" >&2; return 1; }
  # curl, not python's urllib: the KI7MT root carries no keyUsage extension, and Python 3.14's
  # default SSL context rejects such a CA outright ("CA cert does not include key usage
  # extension"). curl accepts it, and it is what vault-secret already uses, so this keeps one
  # TLS behaviour across the lab's tooling instead of two.
  local addr body
  addr="$(vault_addr)" || return 1
  body="$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps({'role_id':d['role_id'],'secret_id':d['secret_id']}))" "$approle")"
  # -d @- reads the body from STDIN. Passing it as -d "$body" put the AppRole secret_id on curl's
  # argv, where any local process could read it with ps for the life of the request.
  printf '%s' "$body" \
    | curl -fsS --cacert "$CA_CERT" -X POST -d @- "$addr/v1/auth/approle/login" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["auth"]["client_token"])' 
}

# cosign <args...> — the pinned container, with Vault reachable and the registry auth mounted.
#
# `-e VAULT_TOKEN` with no value passes the variable through from the environment. Writing
# `-e VAULT_TOKEN="$VAULT_TOKEN"` put the token on docker's argv, readable with ps while signing.
# It is exported by sign_digest for exactly that reason.
#
# VAULT_TOKEN is deliberately optional. Signing needs Vault; VERIFICATION DOES NOT -- it needs only
# the public key and the registry. Referencing it unguarded made `set -u` abort verify-pull with an
# unbound variable before any check could report, which reads as a crash rather than a verdict.
#
# For the same reason the Vault environment is added ONLY when a token is present, i.e. only when
# signing. Reading the AppRole unconditionally meant a machine that has no AppRole -- which is every
# machine a user verifies a release on, and the whole point of publishing the public key -- aborted
# here before cosign ran. Verification must need nothing but the key and the registry.
#
# The array is expanded with the ${a[@]+"${a[@]}"} form: under `set -u` bash 4.3 and earlier treat
# an empty array as unbound, and verify-pull is run on machines we do not choose (macOS ships 3.2).
cosign() {
  local vault=()
  if [ -n "${VAULT_TOKEN:-}" ]; then
    local addr; addr="$(vault_addr)" || return 1
    # -e VAULT_TOKEN with no value: docker copies it from the environment, keeping it off argv.
    vault=(-e VAULT_ADDR="$addr" -e VAULT_TOKEN)
  fi
  docker run --rm \
    ${vault[@]+"${vault[@]}"} \
    -e SSL_CERT_FILE=/ca/root.crt -v "$CA_CERT:/ca/root.crt:ro" \
    -e DOCKER_CONFIG=/dc -v "$DOCKER_CONFIG:/dc:ro" \
    ${SIGN_EXTRA_MOUNT:+-v "$SIGN_EXTRA_MOUNT"} \
    "$COSIGN_IMAGE" "$@"
}

# vault_token_revoke <token> — hand the token back the moment signing is done.
#
# `unset VAULT_TOKEN` only drops our copy: the token stays valid in Vault for the rest of its TTL,
# so a token captured from the process environment outlives the run that made it. revoke-self ends
# it immediately. The token goes in a curl config on STDIN, not in -H on argv, for the same reason
# the AppRole login uses -d @-. Best effort: a release is not failed by a revoke that did not land,
# but it is reported, because a token we believe is dead and is not is worth knowing about.
vault_token_revoke() {
  local token="$1" addr
  addr="$(vault_addr)" || return 0
  printf 'header = "X-Vault-Token: %s"\n' "$token" \
    | curl -fsS -K - --cacert "$CA_CERT" -X POST "$addr/v1/auth/token/revoke-self" >/dev/null \
    || echo "sign: warning: could not revoke the signing token (it expires on its own TTL)" >&2
}

# sign_digest <channel> <image@digest> — sign one digest with the channel's key.
sign_digest() {
  local channel="$1" ref="$2" key tlog
  if [ "$channel" = prod ]; then key="$SIGN_KEY_PROD"; tlog=true; else key="$SIGN_KEY_DEV"; tlog=false; fi
  VAULT_TOKEN="$(vault_token_fresh)" || return 1
  export VAULT_TOKEN          # exported, not passed as an argument: see cosign() above
  # cosign's own error is the whole diagnosis when signing fails; never swallow it.
  local rc=0
  cosign sign --key "hashivault://$key" --tlog-upload="$tlog" -y \
    -a "publisher=ki7mt" -a "channel=$channel" "$ref" || rc=$?
  # Revoked whether signing worked or not: a failed sign leaves a live token just the same.
  vault_token_revoke "$VAULT_TOKEN"
  unset VAULT_TOKEN
  [ $rc -eq 0 ] || return 1
  echo "sign: signed $ref with $key (transparency log: $tlog)"
}

# verify_signed <channel> <pubkey path> <image ref> — 0 signed by us, non-zero otherwise.
# Releases are verified --offline: the Rekor entry is bundled with the signature at signing time,
# so a Sigstore outage cannot turn a good release into a failed check.
# A refusal must say WHY. Discarding cosign's output made every failure look identical -- an
# unsigned image, the wrong key, a network fault and a malformed reference all reported the same
# bare FAIL, and the reason for a refused release is the thing you most need. Quiet on success
# (cosign prints the whole payload), the error on failure.
verify_signed() {
  local channel="$1" pub="$2" ref="$3" flags out rc=0
  if [ "$channel" = prod ]; then flags=(--offline); else flags=(--insecure-ignore-tlog); fi
  out="$(SIGN_EXTRA_MOUNT="$(cd "$(dirname "$pub")" && pwd):/pub:ro" \
    cosign verify --key "/pub/$(basename "$pub")" "${flags[@]}" "$ref" 2>&1)" || rc=$?
  [ $rc -eq 0 ] && return 0
  printf 'verify: cosign refused %s\n' "$ref" >&2
  printf '%s\n' "$out" | sed 's/^/      /' >&2
  return $rc
}
