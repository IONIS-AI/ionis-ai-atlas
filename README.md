# IONIS-AI Atlas

Explore the IONIS-AI propagation collection. React front end, FastAPI API, PostgreSQL with pgvector,
shipped as Docker images on docker.io and run with `docker compose up`.

Build specification: `fleet-ops/packaging/fleet-llm-bench/projects/atlas-web/SPEC.md`.
Data specification: `ionis-core/docs/IONIS-DATA-SPEC.md`.

## Run it

There is no public release yet. From a clone, `make dev` builds and runs the current `main` (see
"Run from a clone" below). Once released:

```
docker compose up          # or: podman compose up
```
then open <http://localhost:8080>. The API's interactive documentation is at <http://localhost:8080/api/docs>.

Images on docker.io, all under `ki7mt`, public: `ki7mt/ionis-ai-atlas` (the app),
`ki7mt/ionis-ai-atlas-db` (the engine) and one `ki7mt/ionis-ai-atlas-data-<dataset>` per dataset.
Development builds go to one private repository, `ki7mt/ionis-ai-atlas-dev`, with the image kind in
the tag (`app-<sha>`, `db-<sha>`).

## What is in it today

**ADIF Reference**: ADIF's bands, modes and submodes, DXCC entities, contest IDs and fields, for
ADIF 3.1.6 and 3.1.7 (current 3.1.7), loaded from adif.org's published files and verified against
their SHA-256 at image build. The database image build fails if the audit does.

## Run from a clone (Docker Desktop)

To run the current `main` without the published images, build them locally:

```
git pull
make dev          # docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```
then open <http://localhost:8080>. Repeat both commands after each pull. `make dev-down` stops the stack.
The development overlay runs the database without its volume, so every rebuild serves the new data.

## Publish (maintainers)

The dev release runs the same process prod will, into **one private** repository,
`ki7mt/ionis-ai-atlas-dev`, with the image kind in the tag.
One machine, one command: on the M3, from a clean checkout of `main`, Docker Desktop builds amd64 and
arm64 together (the non-native one under emulation) and pushes both:

```
make publish                     # on the M3: ionis-ai-atlas-dev:app-<sha> and db-<sha>, amd64 + arm64
make verify-pull TAG=<sha>       # optional, before a release: pull from docker.io, prove it runs
```

Each image carries an SBOM and build provenance as registry attestations.

The push credential comes from Vault (`secret/dockerhub/account/ki7mt`) into a temporary auth file that
is deleted afterwards. Tags are never overwritten. A dev push to a repository that is not private is
refused, and public (prod) pushes are refused until image signing is settled (#8).

## Build and test

```
make images     # both images, from source
make test       # front-end tests, then API tests against a fresh database container
make up         # run the stack from the local images
```

The API tests need `api/requirements.txt` and `api/requirements-test.txt` installed
(`python3.12 -m pip install -r api/requirements.txt -r api/requirements-test.txt`).
`tests/test_compose.py` guards `compose.yaml`: the healthchecks live there, not only in the images,
because podman ignores `HEALTHCHECK` in the OCI-format images the publish step produces.

`db/load/` is vendored from an ionis-core release tag, which is the source of truth for the loader,
the schema and the adif.org checksums: `scripts/sync-from-ionis-core.sh <tag>` updates it, and
`make images` refuses to build if the copy has drifted from what `db/load/SOURCE` records.

`api/openapi.json` is the published `/api/v1` contract. `make openapi` regenerates it and the web
client's types from it; a contract change shows up in review as a diff to that file.

## Licences

Apache-2.0. All runtime dependencies are permissively licensed. One **build-time** tool is not:
`lightningcss` (MPL-2.0), the CSS minifier Vite uses. It is free, needs no key, and nothing from it
ships in the images.
