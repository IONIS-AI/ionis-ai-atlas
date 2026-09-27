# IONIS-AI Atlas

Explore the IONIS-AI propagation collection. React front end, FastAPI API, PostgreSQL with pgvector,
shipped as Docker images on docker.io and run with `docker compose up`.

Build specification: `fleet-ops/packaging/fleet-llm-bench/projects/atlas-web/SPEC.md`.
Data specification: `ionis-core/docs/IONIS-DATA-SPEC.md`.

## Run it

```
docker compose up          # or: podman compose up
```
then open <http://localhost:8080>. The API's interactive documentation is at <http://localhost:8080/api/docs>.

Images on docker.io, all under `ki7mt`: `ki7mt/ionis-ai-atlas` (the app), `ki7mt/ionis-ai-atlas-db`
(the engine) and one `ki7mt/ionis-ai-atlas-data-<dataset>` per dataset. Development images carry a
`-dev` suffix and are private.

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

The dev release runs the same process prod will, into **private** `ki7mt/<image>-dev` repositories.
Each architecture is built natively on its own machine, from a clean checkout of `main`:

```
make publish                     # on 9975 (amd64), then on the M3 (arm64): pushes <image>-dev:<sha>-<arch>
make publish-manifest            # on either, once both are pushed: <image>-dev:<sha> for both architectures
make verify-pull TAG=<sha>       # pull from docker.io and prove the published compose file runs
```

The push credential comes from Vault (`secret/dockerhub/account/ki7mt`) into a temporary auth file that
is deleted afterwards. Tags are never overwritten. A dev push to a repository that is not private is
refused, and public (prod) pushes are refused until image signing is settled (#8).

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
