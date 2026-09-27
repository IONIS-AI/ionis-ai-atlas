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
  addr="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['vault_addr'].rstrip('/'))" "$approle")"
  body="$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps({'role_id':d['role_id'],'secret_id':d['secret_id']}))" "$approle")"
  curl -fsS --cacert "$CA_CERT" -X POST -d "$body" "$addr/v1/auth/approle/login" \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["auth"]["client_token"])' 
}

# cosign <args...> — the pinned container, with Vault reachable and the registry auth mounted.
#
# VAULT_TOKEN is deliberately optional. Signing needs Vault; VERIFICATION DOES NOT -- it needs only
# the public key and the registry. Referencing it unguarded made `set -u` abort verify-pull with an
# unbound variable before any check could report, which reads as a crash rather than a verdict.
# VAULT_ADDR comes from the AppRole file so there is one source of truth for it.
cosign() {
  local addr
  addr="$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('${VAULT_APPROLE_FILE:-$HOME/.config/secrets/vault-approle.json}')))['vault_addr'])")"
  docker run --rm \
    -e VAULT_ADDR="$addr" -e VAULT_TOKEN="${VAULT_TOKEN:-}" \
    -e SSL_CERT_FILE=/ca/root.crt -v "$CA_CERT:/ca/root.crt:ro" \
    -e DOCKER_CONFIG=/dc -v "$DOCKER_CONFIG:/dc:ro" \
    ${SIGN_EXTRA_MOUNT:+-v "$SIGN_EXTRA_MOUNT"} \
    "$COSIGN_IMAGE" "$@"
}

# sign_digest <channel> <image@digest> — sign one digest with the channel's key.
sign_digest() {
  local channel="$1" ref="$2" key tlog
  if [ "$channel" = prod ]; then key="$SIGN_KEY_PROD"; tlog=true; else key="$SIGN_KEY_DEV"; tlog=false; fi
  VAULT_TOKEN="$(vault_token_fresh)" || return 1
  export VAULT_TOKEN
  # cosign's own error is the whole diagnosis when signing fails; never swallow it.
  local rc=0
  cosign sign --key "hashivault://$key" --tlog-upload="$tlog" -y \
    -a "publisher=ki7mt" -a "channel=$channel" "$ref" || rc=$?
  unset VAULT_TOKEN
  [ $rc -eq 0 ] || return 1
  echo "sign: signed $ref with $key (transparency log: $tlog)"
}

# verify_signed <channel> <pubkey path> <image ref> — 0 signed by us, non-zero otherwise.
# Releases are verified --offline: the Rekor entry is bundled with the signature at signing time,
# so a Sigstore outage cannot turn a good release into a failed check.
verify_signed() {
  local channel="$1" pub="$2" ref="$3" flags
  if [ "$channel" = prod ]; then flags=(--offline); else flags=(--insecure-ignore-tlog); fi
  SIGN_EXTRA_MOUNT="$(cd "$(dirname "$pub")" && pwd):/pub:ro" \
    cosign verify --key "/pub/$(basename "$pub")" "${flags[@]}" "$ref" >/dev/null 2>&1
}
