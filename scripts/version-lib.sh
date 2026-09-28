#!/usr/bin/env bash
# version-lib.sh — what release a version belongs to. ONE definition, sourced by publish.sh (which
# creates the stream tag) and verify-pull.sh (which checks it). Written twice, the two drift.

# stream_of <x.y.z> -> the stream that release belongs to (#58).
#
# Semver's own compatibility rule, so no release is a judgement call: while the major is 0 the MINOR
# is the breaking boundary, so the stream is major.minor (0.1.4 -> 0.1); from 1.0.0 the MAJOR is, so
# the stream is the major alone (1.4.2 -> 1).
#
# A stream tag MOVES: it names the newest release in its stream and is not a pin. To pin, name the
# exact version through ATLAS_APP_IMAGE / ATLAS_DB_IMAGE, as the deploy does.
stream_of() {
  local v="$1" major rest minor
  major="${v%%.*}"; rest="${v#*.}"; minor="${rest%%.*}"
  if [ "$major" = 0 ]; then echo "$major.$minor"; else echo "$major"; fi
}
