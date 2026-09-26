# IONIS Atlas

Explore the IONIS-AI propagation collection. React front end, FastAPI API, PostgreSQL with pgvector,
shipped as Docker images on docker.io and run with `docker compose up`.

Build specification: `fleet-ops/packaging/fleet-llm-bench/projects/atlas-web/SPEC.md`.
Data specification: `ionis-core/docs/IONIS-DATA-SPEC.md`.

## Run it

```
docker compose up          # or: podman compose up
```
then open <http://localhost:8080>. The API's interactive documentation is at <http://localhost:8080/api/docs>.

Images on docker.io: `ki7mt/ionis-ai-atlas-dev` and `ki7mt/ionis-ai-atlas-db-dev` (development);
`ionis-ai/ionis-ai-atlas` and `ionis-ai/ionis-ai-atlas-db` once the production account exists.

## What is in it today

**ADIF Reference**: ADIF's bands, modes and submodes, DXCC entities, contest IDs and fields, for
ADIF 3.1.6 and 3.1.7 (current 3.1.7), loaded from adif.org's published files and verified against
their SHA-256 at image build. The database image build fails if the audit does.

## Build and test

```
make images     # both images, from source
make test       # front-end tests, then API tests against a fresh database container
make up         # run the stack from the local images
```

`db/load/` is vendored from an ionis-core release tag, which is the source of truth for the loader,
the schema and the adif.org checksums: `scripts/sync-from-ionis-core.sh <tag>` updates it, and
`make images` refuses to build if the copy has drifted from what `db/load/SOURCE` records.

`api/openapi.json` is the published `/api/v1` contract. `make openapi` regenerates it and the web
client's types from it; a contract change shows up in review as a diff to that file.

## Licences

Apache-2.0. All runtime dependencies are permissively licensed. One **build-time** tool is not:
`lightningcss` (MPL-2.0), the CSS minifier Vite uses. It is free, needs no key, and nothing from it
ships in the images.
