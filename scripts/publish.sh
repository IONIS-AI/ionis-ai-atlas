#!/usr/bin/env bash
# publish.sh — build both images for amd64 AND arm64 in one run and push them to docker.io
# (Atlas SPEC.md, "Deployment"). Runs on the M3: Docker Desktop's buildx builds the non-native
# architecture under emulation, so one machine and one command produce the whole multi-arch release.
# 9975 runs Docker Engine too, but has no arm64 emulation: registering it takes a privileged
# third-party container and does not survive a reboot. So the M3 publishes, and 9975 publishes the
# architecture-independent data images instead (Judge, 2026-09-27).
#
#   scripts/publish.sh        (make publish)
#
# Where images go (Judge, 2026-09-27; Docker Hub's free plan allows one private repository):
#   CHANNEL=dev (default)  ONE private repository, the image kind in the tag:
#                          ki7mt/ionis-ai-atlas-dev:<kind>-<sha>, kind = app | db
#   CHANNEL=prod           one PUBLIC repository per image: ki7mt/ionis-ai-atlas:<version>, ...
#                          Refused until image signing is decided (IONIS-AI/ionis-ai-atlas#8):
#                          nothing public ships unsigned.
#
# Each image carries an SBOM and build provenance as registry attestations (the spec requires both).
#
# Guards, each of which stops the push:
#   * the working tree must be clean, so <sha> names exactly what was built;
#   * a dev repository is created private if absent, and a push to one that is not private is refused;
#   * tags are immutable: a tag that already exists in the registry is never pushed again;
#   * the credential comes from Vault (secret/dockerhub/account/ki7mt) into a temporary auth file
#     that is deleted on exit. No lasting `docker login` is left on the machine.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

CHANNEL="${CHANNEL:-dev}"
KINDS=(app db)                            # app = the React + FastAPI image, db = the engine
PLATFORMS=linux/amd64,linux/arm64
BUILDER=atlas-publish                     # a docker-container buildx builder: multi-platform output

die() { echo "publish: $*" >&2; exit 1; }
[ "$CHANNEL" = dev ] || die "CHANNEL=$CHANNEL refused: public images wait on signing (IONIS-AI/ionis-ai-atlas#8)"
DEV_REPO=ionis-ai-atlas-dev
command -v docker >/dev/null && docker buildx version >/dev/null 2>&1 \
  || die "needs Docker with buildx: run this on the M3 (Docker Desktop)"
# The capability that matters is emulation of the other architecture, which Docker Desktop has built
# in. Check it up front, so a machine without it refuses here instead of failing mid-build on arm64.
case "$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)" in
  *"Docker Desktop"*) ;;
  *) die "builds both architectures only under Docker Desktop (the M3); this machine has no emulation for the other one" ;;
esac

[ -z "$(git status --porcelain)" ] || die "working tree is not clean; commit or stash first"
SHA="$(git rev-parse --short=12 HEAD)"
ENGINE=docker
. scripts/registry-lib.sh     # temporary registry login from Vault, hub()

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

make -s check-vendor
ensure_private_repo "$DEV_REPO"
for kind in "${KINDS[@]}"; do
  tag_exists "$DEV_REPO" "$kind-$SHA" && die "$DEV_REPO:$kind-$SHA already exists; tags are immutable"
done
docker buildx inspect "$BUILDER" >/dev/null 2>&1 \
  || docker buildx create --name "$BUILDER" --driver docker-container >/dev/null
platforms="$(docker buildx inspect --bootstrap "$BUILDER" | sed -n 's/^Platforms: *//p')"
for p in ${PLATFORMS//,/ }; do
  case ",${platforms// /}," in *",$p,"*|*",$p/"*) ;; *) die "builder $BUILDER cannot build $p (has: $platforms)" ;; esac
done

for kind in "${KINDS[@]}"; do
  ref="docker.io/$NAMESPACE/$DEV_REPO:$kind-$SHA"
  if [ "$kind" = db ]; then ctx=db; else ctx=.; fi
  docker buildx build --builder "$BUILDER" --platform "$PLATFORMS" --pull --push \
    --sbom=true --provenance=mode=max \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
    -t "$ref" -f "$ctx/Containerfile" "$ctx"
  echo "publish: pushed $ref ($PLATFORMS)"
done
echo "publish: done. Check it from a clean machine with: make verify-pull TAG=$SHA"
