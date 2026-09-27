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
# DRYRUN=1 runs the entire prod path against a throwaway repository
# (ki7mt/atlas-release-test) instead of the real names, then deletes it. Nothing about the path is
# stubbed: the same tag detection, visibility checks, buildx invocation and push all execute. Run it
# before tagging, so a release is never the first execution of this code.
#
# Where images go (Judge, 2026-09-27; Docker Hub's free plan allows one private repository):
#   CHANNEL=dev (default)  ONE private repository, the image kind in the tag:
#                          ki7mt/ionis-ai-atlas-dev:<kind>-<sha>, kind = app | db
#   CHANNEL=prod           a release: one PUBLIC repository per image, tagged by version:
#                          ki7mt/ionis-ai-atlas:<X.Y.Z>, ki7mt/ionis-ai-atlas-db:<X.Y.Z>.
#                          HEAD must carry the tag vX.Y.Z. Users pull these with no credential.
#                          (Image signing is planned, not required: IONIS-AI/ionis-ai-atlas#8.)
#
# Each image carries an SBOM and build provenance as registry attestations (the spec requires both).
#
# Guards, each of which stops the push:
#   * the working tree must be clean, so <sha> names exactly what was built;
#   * dev repositories are private and prod repositories public: each is created with the right
#     visibility if absent, and a push to one with the wrong visibility is refused;
#   * prod publishes only a commit tagged vX.Y.Z, and the images carry that version;
#   * tags are immutable: a tag that already exists in the registry is never pushed again;
#   * the credential comes from Vault (secret/dockerhub/account/ki7mt) into a temporary auth file
#     that is deleted on exit. No lasting `docker login` is left on the machine.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

CHANNEL="${CHANNEL:-dev}"
DRYRUN="${DRYRUN:-0}"
DRYRUN_REPO=atlas-release-test
KINDS=(app db)                            # app = the React + FastAPI image, db = the engine
PLATFORMS=linux/amd64,linux/arm64
BUILDER=atlas-publish                     # a docker-container buildx builder: multi-platform output

die() { echo "publish: $*" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || die "working tree is not clean; commit or stash first"
SHA="$(git rev-parse --short=12 HEAD)"
# ref_for <kind> → repository and tag for this channel
case "$CHANNEL" in
  dev)  VISIBILITY=private
        ref_for() { echo "ionis-ai-atlas-dev $1-$SHA"; } ;;
  prod) VISIBILITY=public
        # POSIX BRE: \+ is a GNU extension. BSD sed (macOS) reads it as a literal '+', so this
        # matched nothing on the M3 -- the one machine designated to publish releases.
        VERSION="$(git tag --points-at HEAD | sed -n 's/^v\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)$/\1/p' | head -1)"
        # A dry run must work BEFORE the tag exists -- that is when you want it. It stands in a
        # synthetic version and skips the published-tag checks; everything else runs unchanged.
        if [ "$DRYRUN" = 1 ] && [ -z "$VERSION" ]; then VERSION=0.0.0-dryrun; fi
        [ -n "$VERSION" ] || die "CHANNEL=prod publishes a release: tag this commit vX.Y.Z first"
        # The tag must be the PUBLISHED one. Checking only the local tag lets a local-only or
        # locally-moved tag satisfy the guard, and the images then carry an
        # org.opencontainers.image.revision that the released tag does not point at -- provenance
        # nobody else can resolve. That happened on 0.1.0; this is the check that stops it.
        remote_commit="$(git ls-remote origin "refs/tags/v$VERSION^{}" | cut -f1)"
        [ "$DRYRUN" = 1 ] && remote_commit="$(git rev-parse HEAD)"
        [ -n "$remote_commit" ] \
          || die "v$VERSION is not on origin: push the release tag before publishing"
        [ "$remote_commit" = "$(git rev-parse HEAD)" ] \
          || die "origin's v$VERSION points at $(echo "$remote_commit" | cut -c1-12), not HEAD ($(git rev-parse --short=12 HEAD)); push the tag you intend to release"
        ref_for() { case "$1" in app) echo "ionis-ai-atlas $VERSION" ;; db) echo "ionis-ai-atlas-db $VERSION" ;; esac; } ;;
  *)    die "CHANNEL must be dev or prod, not $CHANNEL" ;;
esac
command -v docker >/dev/null && docker buildx version >/dev/null 2>&1 \
  || die "needs Docker with buildx: run this on the M3 (Docker Desktop)"
# The capability that matters is emulation of the other architecture, which Docker Desktop has built
# in. Check it up front, so a machine without it refuses here instead of failing mid-build on arm64.
case "$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)" in
  *"Docker Desktop"*) ;;
  *) die "builds both architectures only under Docker Desktop (the M3); this machine has no emulation for the other one" ;;
esac

ENGINE=docker
. scripts/registry-lib.sh     # temporary registry login from Vault, hub(); defines NAMESPACE
if [ "$DRYRUN" = 1 ]; then
  # Defined outright, not wrapped around the previous definition: wrapping it recurses.
  ref_for() { echo "$DRYRUN_REPO $1-${VERSION:-$SHA}"; }
  echo "publish: DRYRUN — everything below runs for real against $NAMESPACE/$DRYRUN_REPO"
fi

ensure_repo() {           # $1 = repository name; created with $VISIBILITY if absent, refused if it differs
  local code priv want
  [ "$VISIBILITY" = private ] && want=true || want=false
  code="$(hub -o /dev/null -w '%{http_code}' "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$1")"
  if [ "$code" = 404 ]; then
    hub -f -o /dev/null -X POST -H 'Content-Type: application/json' \
      --data "{\"namespace\":\"$NAMESPACE\",\"name\":\"$1\",\"is_private\":$want}" \
      "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories" || die "could not create $NAMESPACE/$1"
    echo "publish: created $NAMESPACE/$1 ($VISIBILITY)"
  fi
  priv="$(hub -f "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$1" | jq -r .is_private)"
  [ "$priv" = "$want" ] || die "$NAMESPACE/$1 is not $VISIBILITY; refusing to push a $CHANNEL image to it"
}
tag_exists() {            # $1 = repository, $2 = tag
  [ "$(hub -o /dev/null -w '%{http_code}' "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$1/tags/$2")" = 200 ]
}

make -s check-vendor
for kind in "${KINDS[@]}"; do
  read -r repo tag <<<"$(ref_for "$kind")"
  ensure_repo "$repo"
  tag_exists "$repo" "$tag" && die "$repo:$tag already exists; tags are immutable"
done
docker buildx inspect "$BUILDER" >/dev/null 2>&1 \
  || docker buildx create --name "$BUILDER" --driver docker-container >/dev/null
platforms="$(docker buildx inspect --bootstrap "$BUILDER" | sed -n 's/^Platforms: *//p')"
for p in ${PLATFORMS//,/ }; do
  case ",${platforms// /}," in *",$p,"*|*",$p/"*) ;; *) die "builder $BUILDER cannot build $p (has: $platforms)" ;; esac
done

for kind in "${KINDS[@]}"; do
  read -r repo tag <<<"$(ref_for "$kind")"
  ref="docker.io/$NAMESPACE/$repo:$tag"
  if [ "$kind" = db ]; then ctx=db; else ctx=.; fi
  # prod also moves :latest, so compose.yaml can default to it and never name a version.
  latest=(); [ "$CHANNEL" = prod ] && latest=(-t "docker.io/$NAMESPACE/$repo:latest")
  docker buildx build --builder "$BUILDER" --platform "$PLATFORMS" --pull --push \
    --sbom=true --provenance=mode=max \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
    --label "org.opencontainers.image.version=${VERSION:-$SHA}" \
    -t "$ref" "${latest[@]}" -f "$ctx/Containerfile" "$ctx"
  echo "publish: pushed $ref ($PLATFORMS)"
done
if [ "$DRYRUN" = 1 ]; then
  # Delete the TAGS, not the repository. Repository deletion on Hub is asynchronous: the repo sits
  # in pending_delete, the registry then grants no scope on it, and the next dry run fails to push.
  # Keeping one repository and clearing its tags makes the dry run repeatable back to back.
  for kind in "${KINDS[@]}"; do
    hub -o /dev/null -X DELETE \
      "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$DRYRUN_REPO/tags/$kind-$VERSION" || true
  done
  echo "publish: DRYRUN passed; cleared the $NAMESPACE/$DRYRUN_REPO tags it pushed"
elif [ "$CHANNEL" = prod ]; then
  echo "publish: released $VERSION. Check it anonymously, as a user would: CHANNEL=prod make verify-pull TAG=$VERSION"
else
  echo "publish: done. Check it from a clean machine with: make verify-pull TAG=$SHA"
fi
