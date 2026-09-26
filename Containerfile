# IONIS Atlas app: the React build and the FastAPI API in one image, on Red Hat UBI 9.
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

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.6
RUN microdnf -y install python3.12 python3.12-pip && microdnf clean all \
 && python3.12 -m venv /opt/atlas && useradd -r -u 1001 -g 0 -d /app atlas
ENV PATH=/opt/atlas/bin:$PATH
WORKDIR /app
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/atlas_api ./atlas_api
COPY --from=web /out/web ./static/web
COPY --from=web /out/swagger ./static/swagger
ENV ATLAS_STATIC=/app/static PYTHONUNBUFFERED=1
EXPOSE 8080
USER 1001
HEALTHCHECK --interval=10s --timeout=5s --retries=6 CMD python3.12 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health',timeout=4).status==200 else 1)"
CMD ["uvicorn", "atlas_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]

LABEL org.opencontainers.image.title="ionis-ai-atlas" \
      org.opencontainers.image.description="IONIS Atlas: React front end and FastAPI API" \
      org.opencontainers.image.source="https://github.com/IONIS-AI/ionis-ai-atlas" \
      org.opencontainers.image.licenses="Apache-2.0"
