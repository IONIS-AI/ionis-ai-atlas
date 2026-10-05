# IONIS-AI Atlas — build, test and run the two images locally.
#   make images      build ionis-ai-atlas and ionis-ai-atlas-db (docker format keeps HEALTHCHECK)
#                    fresh packages by default (no cache); FRESH=0 reuses the cache
#   make test        API tests against a fresh database container, plus the front-end tests
#   make up / down   run the stack from the local images (http://127.0.0.1:8080)
#   make dev         Docker (Desktop): build both images from this checkout and run them; after a
#                    `git pull`, `make dev` again picks up the changes. `make dev-down` stops it.
#   make publish     on the M3 (Docker Desktop): build amd64 + arm64 and push
#                    ki7mt/ionis-ai-atlas-dev:<kind>-<sha> (one private repository; kind = app | db).
#                    CHANNEL=prod make publish on a commit tagged vX.Y.Z: public ki7mt/ionis-ai-atlas:X.Y.Z
#   make verify-pull TAG=<sha>   pull from docker.io and prove the published compose file runs
#   make release-dryrun   run the whole prod publish path against a throwaway repository, then
#                    delete it. Run it BEFORE tagging: a release should never be this code's
#                    first execution.
#   make scan        scan the local images for vulnerabilities; fails on any fixable HIGH or CRITICAL
#                    (scripts/scan.sh holds the threshold; the nightly workflow scans the release)
#   make rehearse-adif  prove a new ADIF version drops in with no code change: 3.1.6-only engine,
#                    upgraded in place to the release, same tests (SPEC R17)
#   make check-ui    drive the ADIF section in headless Chromium: paging, search, names (R15, R16)
#   make check-browser  render both pages in headless Chromium and fail on anything the CSP blocks
#                    (needs the stack up: `make dev` or `make up` first)
ENGINE ?= podman
TAG    ?= dev
LOCAL  := ATLAS_APP_IMAGE=localhost/ionis-ai-atlas:$(TAG) ATLAS_DB_IMAGE=localhost/ionis-ai-atlas-db:$(TAG)
PY     ?= python3.12

.PHONY: images openapi check-vendor test up down dev dev-down publish verify-pull check-browser check-ui rehearse-adif release-dryrun scan

check-vendor:
	scripts/sync-from-ionis-core.sh --check

openapi:
	$(PY) scripts/gen-openapi.py
	cd web && npm run -s gen:api

# podman writes OCI images by default, and podman ignores HEALTHCHECK in OCI format; Docker writes
# docker format already and has no --format flag. So the flag is podman's alone.
FORMAT := $(if $(filter podman,$(ENGINE)),--format docker,)

# The Containerfiles' `dnf upgrade` line never changes, so a cached layer keeps old packages and
# `make scan` fails on CVEs already fixed upstream (ionis-ai-atlas#78). So `images` builds fresh by
# default; FRESH=0 reuses the cache for a quick local iteration.
FRESH ?= 1
NOCACHE := $(if $(filter 0,$(FRESH)),,--no-cache --pull)

images: check-vendor
	$(ENGINE) build $(FORMAT) $(NOCACHE) -t localhost/ionis-ai-atlas-db:$(TAG) -f db/Containerfile db
	$(ENGINE) build $(FORMAT) $(NOCACHE) -t localhost/ionis-ai-atlas:$(TAG) -f Containerfile .

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

release-dryrun:
	DRYRUN=1 CHANNEL=prod scripts/publish.sh

verify-pull:
	scripts/verify-pull.sh $(TAG)

scan:
	ENGINE=$(ENGINE) scripts/scan.sh localhost/ionis-ai-atlas:$(TAG) localhost/ionis-ai-atlas-db:$(TAG)

# The CSP is enforced by the browser, so nothing server-side can prove the pages still work under
# it. BASE overrides the URL; the stack must already be running.
BASE ?= http://localhost:8080

check-browser:
	@if command -v uv >/dev/null; then \
	  uv run --with playwright python scripts/check-browser.py $(BASE); \
	else \
	  $(PY) scripts/check-browser.py $(BASE); \
	fi

rehearse-adif:
	ENGINE=$(ENGINE) PY=$(PY) scripts/rehearse-adif-version.sh

check-ui:
	@if command -v uv >/dev/null; then \
	  uv run --with playwright python scripts/check-ui.py $(BASE); \
	else \
	  $(PY) scripts/check-ui.py $(BASE); \
	fi
