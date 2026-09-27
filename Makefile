# IONIS-AI Atlas — build, test and run the two images locally.
#   make images      build ionis-ai-atlas and ionis-ai-atlas-db (docker format keeps HEALTHCHECK)
#   make test        API tests against a fresh database container, plus the front-end tests
#   make up / down   run the stack from the local images (http://127.0.0.1:8080)
#   make dev         Docker (Desktop): build both images from this checkout and run them; after a
#                    `git pull`, `make dev` again picks up the changes. `make dev-down` stops it.
#   make publish     on the M3 (Docker Desktop): build amd64 + arm64 and push
#                    ki7mt/ionis-ai-atlas-dev:<kind>-<sha> (one private repository; kind = app | db).
#                    CHANNEL=prod make publish on a commit tagged vX.Y.Z: public ki7mt/ionis-ai-atlas:X.Y.Z
#   make verify-pull TAG=<sha>   pull from docker.io and prove the published compose file runs
#   make check-browser  render both pages in headless Chromium and fail on anything the CSP blocks
#                    (needs the stack up: `make dev` or `make up` first)
ENGINE ?= podman
TAG    ?= dev
LOCAL  := ATLAS_APP_IMAGE=localhost/ionis-ai-atlas:$(TAG) ATLAS_DB_IMAGE=localhost/ionis-ai-atlas-db:$(TAG)
PY     ?= python3.12

.PHONY: images openapi check-vendor test up down dev dev-down publish verify-pull check-browser

check-vendor:
	scripts/sync-from-ionis-core.sh --check

openapi:
	$(PY) scripts/gen-openapi.py
	cd web && npm run -s gen:api

images: check-vendor
	$(ENGINE) build --format docker -t localhost/ionis-ai-atlas-db:$(TAG) -f db/Containerfile db
	$(ENGINE) build --format docker -t localhost/ionis-ai-atlas:$(TAG) -f Containerfile .

test:
	cd web && npm run -s test
	-$(ENGINE) rm -f atlas-db-test >/dev/null 2>&1
	$(ENGINE) run -d --name atlas-db-test -p 127.0.0.1:55433:5432 localhost/ionis-ai-atlas-db:$(TAG)
	until $(ENGINE) exec atlas-db-test pg_isready -h 127.0.0.1 -d ionis -U atlas_ro >/dev/null 2>&1; do sleep 1; done
	cd api && ATLAS_DB_URL=postgresql://atlas_ro:atlas@127.0.0.1:55433/ionis ATLAS_STATIC=/nonexistent $(PY) -m pytest -q tests; rc=$$?; $(ENGINE) rm -f atlas-db-test >/dev/null; exit $$rc

up:
	$(LOCAL) $(ENGINE) compose up -d

down:
	$(LOCAL) $(ENGINE) compose down

DEV := docker compose -f compose.yaml -f compose.dev.yaml

dev: check-vendor
	$(DEV) up -d --build

dev-down:
	$(DEV) down

publish:
	scripts/publish.sh

verify-pull:
	scripts/verify-pull.sh $(TAG)

# The CSP is enforced by the browser, so nothing server-side can prove the pages still work under
# it. BASE overrides the URL; the stack must already be running.
BASE ?= http://localhost:8080

check-browser:
	@if command -v uv >/dev/null; then \
	  uv run --with playwright python scripts/check-browser.py $(BASE); \
	else \
	  $(PY) scripts/check-browser.py $(BASE); \
	fi
