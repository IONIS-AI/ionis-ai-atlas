#!/usr/bin/env bash
# scan.sh — scan Atlas images for known vulnerabilities; exit non-zero when one needs fixing.
#
#   scripts/scan.sh localhost/ionis-ai-atlas:dev localhost/ionis-ai-atlas-db:dev   # images just built
#   scripts/scan.sh docker.io/ki7mt/ionis-ai-atlas:0.1.1                          # a published image
#
# THE THRESHOLD, defined here and nowhere else (`make scan`, the publish gate and the nightly
# workflow all call this script): an image fails on any CRITICAL or HIGH vulnerability that has a
# fix available. A finding with no fix yet is listed but does not fail: nothing we can build would
# remove it. ionis-ai-atlas#18.
#
# Trivy runs in a container pinned by digest, so nothing is installed and every machine runs the
# same scanner. A scanner reads everything it scans, so the version is chosen, never "latest".
#
# Environment:
#   ENGINE    docker | podman (default: whichever is installed, docker first)
#   PLATFORM  for a published multi-arch image, e.g. linux/arm64 (default: linux/amd64)
#   SARIF_DIR also write a SARIF report per image there (the nightly workflow uploads them)
set -euo pipefail

# Trivy 0.74.0 (aquasec/trivy on docker.io; the digest matches the v0.74.0 GitHub release).
TRIVY_IMAGE="docker.io/aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969"
# shellcheck disable=SC2054   # HIGH,CRITICAL is one argument: Trivy's comma-separated list
THRESHOLD=(--severity HIGH,CRITICAL --ignore-unfixed)

ENGINE="${ENGINE:-$(command -v docker >/dev/null && echo docker || echo podman)}"
PLATFORM="${PLATFORM:-linux/amd64}"
[ $# -gt 0 ] || { echo "usage: $0 IMAGE [IMAGE...]" >&2; exit 2; }

# The vulnerability database lives in a volume the engine manages, not a host directory: Docker's
# container runs as root and leaves root-owned files that rootless podman then cannot write, and a
# host directory needs SELinux relabelling. A named volume behaves the same under Docker, podman
# and Docker Desktop.
CACHE_VOLUME=ionis-ai-atlas-trivy-cache
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Trivy exits 1 when it FAILS to run (no database, unreadable image). Findings get their own code,
# so a broken scanner is reported as broken, never as "vulnerable" or, worse, as clean.
FOUND=3

trivy() {
  "$ENGINE" run --rm -v "$CACHE_VOLUME:/root/.cache/trivy" -v "$WORK:/work:z" "$TRIVY_IMAGE" "$@"
}

failed=0
for image in "$@"; do
  name="$(basename "${image%%[:@]*}")"
  if [[ "$image" == localhost/* ]]; then
    # A local build: the scanner's container cannot see the host's image store, so hand it a tarball.
    # No -q: podman save accepts it, docker save does not ("unknown shorthand flag: 'q'"), and
    # this runs on the publisher, which is Docker Desktop. -o is already quiet on stdout.
    "$ENGINE" save -o "$WORK/$name.tar" "$image"
    source=(--input "/work/$name.tar")
    echo "== $image (local build)"
  else
    source=(--image-src remote --platform "$PLATFORM" "$image")
    echo "== $image ($PLATFORM)"
  fi

  rc=0
  trivy image --quiet --scanners vuln "${THRESHOLD[@]}" --exit-code "$FOUND" "${source[@]}" || rc=$?
  case "$rc" in
    0)        echo "PASS  $image: no fixable HIGH or CRITICAL vulnerabilities" ;;
    "$FOUND") echo "FAIL  $image: fixable HIGH or CRITICAL vulnerabilities (above). Rebuild on current packages."
              failed=1 ;;
    *)        echo "ERROR $image: the scanner did not run (exit $rc, above). This is not a result."
              exit 2 ;;
  esac

  if [ -n "${SARIF_DIR:-}" ]; then
    mkdir -p "$SARIF_DIR"
    trivy image --quiet --scanners vuln "${THRESHOLD[@]}" --format sarif -o "/work/$name.sarif" "${source[@]}"
    cp "$WORK/$name.sarif" "$SARIF_DIR/$name-${PLATFORM//\//-}.sarif"
  fi
  rm -f "$WORK/$name.tar"
done
exit "$failed"
