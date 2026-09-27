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

# The release identity goes into the image (ionis-ai-atlas#30) and must be IDENTICAL on the builds
# that are scanned and the build that is pushed. The ARG changes an ENV and a RUN layer, so passing
# it to only one of them makes the pushed image a different image from the one that passed the
# scan -- the gate would then be attesting to something nobody ships.
VERSION_ARGS=()

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
VERSION_ARGS=(--build-arg "ATLAS_VERSION=${VERSION:-$SHA}" --build-arg "ATLAS_REVISION=$(git rev-parse HEAD)")
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
. scripts/sign-lib.sh         # cosign + Vault transit: sign_digest, verify_signed
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

# THE GATE (ionis-ai-atlas#18). Nothing is pushed until every architecture has been scanned and
# passed. A multi-arch `--push` build leaves nothing on this machine to scan, and scan.sh's remote
# mode pulls anonymously, so it cannot read the private dev repository either. So each platform is
# built with --load first, scanned locally, and only then is the combined multi-arch image pushed.
# The second build reuses the builder's cache, so the push costs a fraction of the first build.
#
# scan.sh's exit codes: 0 pass, 1 fixable HIGH/CRITICAL, 2 the scanner did not run. 2 stops the
# publish exactly like 1 — a scanner that did not run is not a pass.
scan_local() {                     # $1 = kind, $2 = context dir
  local kind="$1" ctx="$2" plat arch scan_tag rc
  for plat in ${PLATFORMS//,/ }; do
    arch="${plat##*/}"
    scan_tag="localhost/atlas-scan-$kind:$arch"
    echo "publish: building $kind for $plat to scan it"
    docker buildx build --builder "$BUILDER" --platform "$plat" --pull --load \
      "${VERSION_ARGS[@]}" \
      -t "$scan_tag" -f "$ctx/Containerfile" "$ctx" >/dev/null
    rc=0; ENGINE=docker scripts/scan.sh "$scan_tag" || rc=$?
    docker image rm -f "$scan_tag" >/dev/null 2>&1 || true
    case "$rc" in
      0) ;;
      1) die "$kind ($plat) has fixable HIGH/CRITICAL vulnerabilities; nothing was pushed" ;;
      *) die "$kind ($plat): the scanner did not run (exit $rc); refusing to publish unscanned images" ;;
    esac
  done
}

for kind in "${KINDS[@]}"; do
  if [ "$kind" = db ]; then ctx=db; else ctx=.; fi
  scan_local "$kind" "$ctx"
done

# Push to a STAGING tag, sign the index digest, and only then create the tags people pull.
#
# Signing must follow the push -- cosign signs a digest that exists in a registry. But the RELEASE
# tag does not have to exist unsigned first, and on a public repository it must not: it would be
# pullable-and-unsigned in the gap, and a signing failure would leave a published release to
# retract. Cosign signatures are digest-scoped, not tag-scoped, so a tag created afterwards from
# the same digest is signed from the instant it exists.
#
# A failure before the final step therefore leaves only a staging tag to clean up, and no
# user-facing tag was ever created.
for kind in "${KINDS[@]}"; do
  read -r repo tag <<<"$(ref_for "$kind")"
  staging="_staging-$tag"
  ref="docker.io/$NAMESPACE/$repo:$tag"
  stage_ref="docker.io/$NAMESPACE/$repo:$staging"
  if [ "$kind" = db ]; then ctx=db; else ctx=.; fi

  drop_staging() { hub -o /dev/null -X DELETE \
    "https://hub.docker.com/v2/namespaces/$NAMESPACE/repositories/$repo/tags/$staging" >/dev/null 2>&1 || true; }

  docker buildx build --builder "$BUILDER" --platform "$PLATFORMS" --pull --push \
    --sbom=true --provenance=mode=max \
    "${VERSION_ARGS[@]}" \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
    --label "org.opencontainers.image.version=${VERSION:-$SHA}" \
    -t "$stage_ref" -f "$ctx/Containerfile" "$ctx"

  digest="$(docker buildx imagetools inspect "$stage_ref" --format '{{.Manifest.Digest}}')"
  [ -n "$digest" ] || { drop_staging; die "could not read the index digest of $stage_ref"; }

  # One signature on the multi-arch index covers both architectures, and the SBOM and provenance
  # with them: the index lists those manifests by digest, so altering one changes the index digest
  # and breaks this signature.
  # A DRY RUN MUST NOT MINT A RELEASE SIGNATURE. make release-dryrun runs with CHANNEL=prod so the
  # real path is exercised, but signing with the release key would produce an artefact
  # indistinguishable from a genuine release, and upload its digest to the public, permanent,
  # append-only transparency log. A rehearsal signs with the dev key and never uploads.
  sign_channel="$CHANNEL"; [ "$DRYRUN" = 1 ] && sign_channel=dev
  sign_digest "$sign_channel" "docker.io/$NAMESPACE/$repo@$digest" \
    || { drop_staging; die "signing failed for $kind; nothing user-facing was created"; }

  # prod also moves :latest, so compose.yaml can default to it and never name a version. Both tags
  # are the same already-signed digest.
  latest=(); [ "$CHANNEL" = prod ] && latest=(-t "docker.io/$NAMESPACE/$repo:latest")
  docker buildx imagetools create -t "$ref" "${latest[@]}" "docker.io/$NAMESPACE/$repo@$digest" >/dev/null
  drop_staging
  echo "publish: pushed $ref ($PLATFORMS), signed"
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
