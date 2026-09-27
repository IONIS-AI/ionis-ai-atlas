# IONIS-AI Atlas app: the React build and the FastAPI API in one image, on Red Hat UBI 9.
# Stage 1 builds the front end (Node only here); stage 2 is the runtime: UBI minimal with only
# Python 3.12 (the full ubi9/python-312 developer image made this 1.13 GB).

FROM registry.access.redhat.com/ubi9/nodejs-20 AS web
USER 0
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
COPY api/openapi.json /src/api/openapi.json
RUN npm run gen:api && npm run build \
 && mkdir -p /out/swagger \
 && cp node_modules/swagger-ui-dist/swagger-ui-bundle.js node_modules/swagger-ui-dist/swagger-ui.css \
       node_modules/swagger-ui-dist/favicon-32x32.png node_modules/swagger-ui-dist/LICENSE /out/swagger/ \
 && cp -r dist /out/web

# The current UBI 9 minor, not a pinned one, and every package brought up to date. Red Hat ships
# fixes on the current stream: 0.1.0 was built on a pinned 9.6 without an upgrade and carried 27
# fixable HIGH vulnerabilities that were already fixed in 9.8 (ionis-ai-atlas#18).
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
WORKDIR /app
COPY api/requirements.txt ./
# pip is needed to install the dependencies and never at run time, so it leaves the image in the same
# layer: the venv's copy and the RPM. Neither can then carry a finding.
RUN microdnf -y upgrade --refresh \
 && microdnf -y install python3.12 python3.12-pip \
 && python3.12 -m venv /opt/atlas \
 && /opt/atlas/bin/pip install --no-cache-dir -r requirements.txt \
 && /opt/atlas/bin/pip uninstall -y pip \
 && microdnf -y remove python3.12-pip \
 && microdnf clean all \
 && useradd -r -u 1001 -g 0 -d /app atlas
ENV PATH=/opt/atlas/bin:$PATH
COPY api/atlas_api ./atlas_api
# The release and git revision, reported by /api/v1/version and the API description. publish.sh
# passes both; a build without them reports "dev" / "unknown". Declared late so a new version only
# rebuilds these last layers, not the dependency install above.
#
# The RUN is what makes the version reliable. podman/buildah reuse a cached `ENV X=$ARG` layer even
# when the ARG changed, so a second local build kept reporting the FIRST build's version (measured:
# two tags, one image ID, both "dev"). Every engine keys a RUN's cache on the ARGs it uses, so a new
# version invalidates this layer and everything after it. It also leaves /app/RELEASE in the image.
ARG ATLAS_VERSION=dev
ARG ATLAS_REVISION=unknown
RUN printf '%s %s\n' "$ATLAS_VERSION" "$ATLAS_REVISION" > /app/RELEASE
ENV ATLAS_VERSION=$ATLAS_VERSION ATLAS_REVISION=$ATLAS_REVISION
COPY --from=web /out/web ./static/web
COPY --from=web /out/swagger ./static/swagger
ENV ATLAS_STATIC=/app/static PYTHONUNBUFFERED=1
EXPOSE 8080
USER 1001
HEALTHCHECK --interval=10s --timeout=5s --retries=6 CMD python3.12 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health',timeout=4).status==200 else 1)"
CMD ["uvicorn", "atlas_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

LABEL org.opencontainers.image.title="ionis-ai-atlas" \
      org.opencontainers.image.description="IONIS-AI Atlas: React front end and FastAPI API" \
      org.opencontainers.image.source="https://github.com/IONIS-AI/ionis-ai-atlas" \
      org.opencontainers.image.licenses="Apache-2.0"
