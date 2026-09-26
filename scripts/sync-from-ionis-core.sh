#!/usr/bin/env bash
# sync-from-ionis-core.sh — vendor the ADIF loader from an ionis-core release tag, and check it.
#   scripts/sync-from-ionis-core.sh v4.6.0          copy the three files from that tag, rewrite SOURCE
#   scripts/sync-from-ionis-core.sh --check         exit 1 if db/load differs from what SOURCE records
# ionis-core is the source of truth for the loader, the schema and the adif.org pins; this repo only
# carries a copy pinned to a tag, so the database image never builds from a private checkout.
set -euo pipefail
cd "$(dirname "$0")/../db/load"
FILES=(adif_tier.py 10-adif_schema.sql adif_upstream_sha256.json)
if [[ "${1:-}" == "--check" ]]; then
  tail -n +2 SOURCE | sha256sum --check --quiet && echo "db/load matches $(head -1 SOURCE)"; exit
fi
tag="${1:?usage: $0 <ionis-core tag> | --check}"
core="${IONIS_CORE:-${WORKSPACE_ROOT:-$HOME/workspace}/ionis-ai/ionis-core}"
git -C "$core" fetch -q --tags
git -C "$core" show "$tag:scripts/adif_tier.py"             > adif_tier.py
git -C "$core" show "$tag:src/pg/10-adif_schema.sql"        > 10-adif_schema.sql
git -C "$core" show "$tag:data/adif_upstream_sha256.json"   > adif_upstream_sha256.json
{ echo "ionis-core $tag ($(git -C "$core" rev-parse --short "$tag^{}"))"; sha256sum "${FILES[@]}"; } > SOURCE
echo "synced from ionis-core $tag"
