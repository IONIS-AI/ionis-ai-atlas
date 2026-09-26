# IONIS-AI Atlas — build, test and run the two images locally.
#   make images      build ionis-ai-atlas and ionis-ai-atlas-db (docker format keeps HEALTHCHECK)
#   make test        API tests against a fresh database container, plus the front-end tests
#   make up / down   run the stack from the local images (http://127.0.0.1:8080)
ENGINE ?= podman
TAG    ?= dev
LOCAL  := ATLAS_REGISTRY=localhost ATLAS_APP=ionis-ai-atlas ATLAS_DB=ionis-ai-atlas-db ATLAS_TAG=$(TAG)
PY     ?= python3.12

.PHONY: images openapi check-vendor test up down

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
