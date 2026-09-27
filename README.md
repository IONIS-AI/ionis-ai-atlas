# IONIS-AI Atlas

[![Image scan](https://github.com/IONIS-AI/ionis-ai-atlas/actions/workflows/scan.yml/badge.svg)](https://github.com/IONIS-AI/ionis-ai-atlas/actions/workflows/scan.yml)

Explore the IONIS-AI propagation collection. React front end, FastAPI API, PostgreSQL with pgvector,
shipped as Docker images on docker.io and run with `docker compose up`.

Build specification: `fleet-ops/packaging/fleet-llm-bench/projects/atlas-web/SPEC.md`.
Data specification: `ionis-core/docs/IONIS-DATA-SPEC.md`.

## Run it

You need Docker (or podman) and the `compose.yaml` file from a release. Nothing else: no account,
no login, no clone.

```
curl -O https://raw.githubusercontent.com/IONIS-AI/ionis-ai-atlas/v0.1.0/compose.yaml
docker compose up          # or: podman compose up
```
then open <http://localhost:8080>. To upgrade, fetch the new release's `compose.yaml` and run it again. The API's interactive documentation is at <http://localhost:8080/api/docs>.

Images on docker.io, all under `ki7mt`, public, tagged by release version: `ki7mt/ionis-ai-atlas` (the app),
`ki7mt/ionis-ai-atlas-db` (the engine) and one `ki7mt/ionis-ai-atlas-data-<dataset>` per dataset.
Development builds go to one private repository, `ki7mt/ionis-ai-atlas-dev`, with the image kind in
the tag (`app-<sha>`, `db-<sha>`).

## Serve it over HTTPS (a server, VM or another machine)

Atlas answers plain HTTP on `127.0.0.1:8080` only, so by default only the machine running it can
reach it. To open it to other machines, keep it that way and put an HTTPS reverse proxy in front,
with a certificate for the name you will use: one from your own CA, Let's Encrypt, or any other.
Don't publish port 8080 on other addresses. That would serve it without encryption, and Atlas would
refuse the requests anyway (below).

Atlas accepts only requests addressed to `localhost` or `127.0.0.1`. This protects against DNS
rebinding, where a hostile web page points a name it controls at your machine. So the proxy has to:

- accept only the names you serve Atlas under, and refuse the rest;
- forward to `http://127.0.0.1:8080` with the `Host` header set to `localhost`.

With nginx:

```nginx
server {                                   # any other name: refused
    listen 443 ssl default_server;
    ssl_certificate     /etc/nginx/tls/atlas.crt;
    ssl_certificate_key /etc/nginx/tls/atlas.key;
    return 421;
}
server {
    listen 443 ssl;
    server_name atlas.example.org 192.0.2.10;   # your name(s) and, optionally, the IP
    ssl_certificate     /etc/nginx/tls/atlas.crt;
    ssl_certificate_key /etc/nginx/tls/atlas.key;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host localhost;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

To reach Atlas by IP address, the certificate must list that IP as well as the name. On RHEL, Rocky or
other SELinux systems, let the proxy connect to Atlas: `setsebool -P httpd_can_network_relay on`.

Tested with the published release on a Rocky Linux 9 VM (SELinux enforcing): nginx with a
certificate from a private CA, reached from other machines by DNS name and by IP. Certificates
verified, and requests under any other name were refused.

### Host prerequisites: Rocky Linux 9 / RHEL 9

This is everything the host needs. Atlas brings everything else in its containers.

1. **Docker Engine**, from Docker's repository for RHEL. Remove podman's `docker` shim first, because
   it conflicts:
   ```
   sudo dnf remove -y podman-docker
   sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
   sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
   sudo systemctl enable --now docker
   ```
2. **nginx**, from AppStream: `sudo dnf install -y nginx && sudo systemctl enable --now nginx`
   (after adding the configuration above).
3. **SELinux**: let nginx connect to Atlas: `sudo setsebool -P httpd_can_network_relay on`.
4. **Firewall**, if firewalld is running:
   ```
   sudo firewall-cmd --permanent --add-service=http --add-service=https
   sudo firewall-cmd --reload
   ```

If your certificate comes from a **private CA**, the machines that connect to Atlas must trust that
CA's root. On Rocky or RHEL, copy it into `/etc/pki/ca-trust/source/anchors/` and run
`sudo update-ca-trust`. A certificate from a public CA needs no extra step.

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

A **release** is the same command on a commit tagged `vX.Y.Z`, into the public repositories:

```
git tag v0.1.0 && git push origin v0.1.0            # the tag compose.yaml's version names
CHANNEL=prod make publish                           # on the M3: ki7mt/ionis-ai-atlas:0.1.0, -db:0.1.0
CHANNEL=prod make verify-pull TAG=0.1.0             # on the M3 and 9975: pulls with no login at all
```

Each image carries an SBOM and build provenance as registry attestations.

The push credential comes from Vault (`secret/dockerhub/account/ki7mt`) into a temporary auth file that
is deleted afterwards. Tags are never overwritten. A dev push to a repository that is not private is
refused, as is a prod push to a repository that is not public. Image signing is planned (#8), not
required.

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

### Vulnerability scanning

```
make scan       # scan the local images; fails on any HIGH or CRITICAL vulnerability that has a fix
```

`scripts/scan.sh` holds the one threshold everything uses: an image fails on a HIGH or CRITICAL
vulnerability **that has a fix available**. A finding with no fix yet is listed but doesn't fail,
because no rebuild could remove it. The scanner is [Trivy](https://trivy.dev), run in a container
pinned by digest, so there's nothing to install. The images build on the current UBI 9 release with
every package upgraded.

The **Image scan** badge above is a nightly scan of the released images
(`.github/workflows/scan.yml`). A published image never changes, but new vulnerabilities are
announced against it all the time. When the badge turns red, the scan has opened an issue: rebuild on
current packages and publish a patch release. Findings appear in the repository's Security tab.

`db/load/` is vendored from an ionis-core release tag, which is the source of truth for the loader,
the schema and the adif.org checksums: `scripts/sync-from-ionis-core.sh <tag>` updates it, and
`make images` refuses to build if the copy has drifted from what `db/load/SOURCE` records.

`api/openapi.json` is the published `/api/v1` contract. `make openapi` regenerates it and the web
client's types from it; a contract change shows up in review as a diff to that file.

## Licences

Apache-2.0. All runtime dependencies are permissively licensed. One **build-time** tool is not:
`lightningcss` (MPL-2.0), the CSS minifier Vite uses. It is free, needs no key, and nothing from it
ships in the images.
