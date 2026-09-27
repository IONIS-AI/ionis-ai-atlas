#!/usr/bin/env bash
# publish.sh — push this checkout's images to docker.io (Atlas SPEC.md, "Deployment").
#
#   scripts/publish.sh arch        build both images for THIS machine's architecture and push
#                                  ki7mt/<image>-dev:<sha>-<arch>          (run on 9975 and on the M3)
#   scripts/publish.sh manifest    join the pushed architectures into ki7mt/<image>-dev:<sha>
#
# CHANNEL=dev (default) pushes private *-dev repositories. CHANNEL=prod is refused until image
# signing is decided (IONIS-AI/ionis-ai-atlas#8): nothing public ships unsigned.
#
# Guards, each of which stops the push:
#   * the working tree must be clean, so <sha> names exactly what was built;
#   * a dev repository is created private if absent, and a push to one that is not private is refused;
#   * tags are immutable: a tag that already exists in the registry is never pushed again;
#   * the credential comes from Vault (secret/dockerhub/account/ki7mt) into a temporary auth file
#     that is deleted on exit. No lasting `docker login` is left on the machine.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

MODE="${1:?usage: $0 arch|manifest}"
CHANNEL="${CHANNEL:-dev}"
IMAGES=(ionis-ai-atlas ionis-ai-atlas-db)
ARCHES=(amd64 arm64)

die() { echo "publish: $*" >&2; exit 1; }
[ "$CHANNEL" = dev ] || die "CHANNEL=$CHANNEL refused: public images wait on signing (IONIS-AI/ionis-ai-atlas#8)"
SUFFIX=-dev

[ -z "$(git status --porcelain)" ] || die "working tree is not clean; commit or stash first"
SHA="$(git rev-parse --short=12 HEAD)"
case "$(uname -m)" in x86_64|amd64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) die "unsupported architecture $(uname -m)" ;; esac
. scripts/registry-lib.sh     # ENGINE, temporary registry login, hub()

# --- guards -----------------------------------------------------------------------------------------
ensure_private_repo() {   # $1 = repository name
  local code priv
  code="$(hub -o /dev/null -w '%{http_code}' "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$1")"
  if [ "$code" = 404 ]; then
    hub -f -o /dev/null -X POST -H 'Content-Type: application/json' \
      --data "{\"namespace\":\"$NAMESPACE\",\"name\":\"$1\",\"is_private\":true}" \
      "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories" || die "could not create $NAMESPACE/$1"
    echo "publish: created $NAMESPACE/$1 (private)"
  fi
  priv="$(hub -f "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$1" | jq -r .is_private)"
  [ "$priv" = true ] || die "$NAMESPACE/$1 is not private; refusing to push a dev image to it"
}
tag_exists() {            # $1 = repository, $2 = tag
  [ "$(hub -o /dev/null -w '%{http_code}' "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$1/tags/$2")" = 200 ]
}

# --- modes ------------------------------------------------------------------------------------------
if [ "$MODE" = arch ]; then
  make -s check-vendor
  for img in "${IMAGES[@]}"; do
    repo="$img$SUFFIX"; ref="docker.io/$NAMESPACE/$repo:$SHA-$ARCH"
    ensure_private_repo "$repo"
    tag_exists "$repo" "$SHA-$ARCH" && die "$ref already exists; tags are immutable"
    if [ "$img" = ionis-ai-atlas-db ]; then ctx=db; else ctx=.; fi
    fmt=(); [ "$ENGINE" = podman ] && fmt=(--format docker)   # docker format keeps HEALTHCHECK
    $ENGINE build "${fmt[@]}" --pull -t "$ref" \
      --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" -f "$ctx/Containerfile" "$ctx"
    $ENGINE push "$ref"
    echo "publish: pushed $ref"
  done
elif [ "$MODE" = manifest ]; then
  for img in "${IMAGES[@]}"; do
    repo="$img$SUFFIX"; ref="docker.io/$NAMESPACE/$repo:$SHA"
    for a in "${ARCHES[@]}"; do tag_exists "$repo" "$SHA-$a" || die "$repo:$SHA-$a not pushed yet; run 'make publish' on the $a machine"; done
    tag_exists "$repo" "$SHA" && die "$ref already exists; tags are immutable"
    if [ "$ENGINE" = podman ]; then
      podman manifest rm "$ref" >/dev/null 2>&1 || true
      podman manifest create "$ref" >/dev/null
      for a in "${ARCHES[@]}"; do podman manifest add "$ref" "docker://docker.io/$NAMESPACE/$repo:$SHA-$a" >/dev/null; done
      podman manifest push --all "$ref" "docker://$ref"
      podman manifest rm "$ref" >/dev/null
    else
      docker buildx imagetools create -t "$ref" $(for a in "${ARCHES[@]}"; do echo "docker.io/$NAMESPACE/$repo:$SHA-$a"; done)
    fi
    echo "publish: pushed $ref (${ARCHES[*]})"
  done
else
  die "unknown mode $MODE"
fi
