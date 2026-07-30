FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# NOTE: the build context is the REPOSITORY ROOT, not this directory (see `context: .` in
# docker-compose.yml), because the image needs the shared laboratory_client as well as this
# server's own package. Every COPY path below is therefore repo-relative, and .dockerignore
# is what keeps that wider context small.

# Third-party dependencies first, so editing our own sources does not invalidate this layer.
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir sila2 typer

# Both of our own trees are staged under /tmp and deleted in the same layer as their
# install, so the runtime image carries only what pip put in site-packages: nothing to keep
# in sync with the installed copy, and no source tree left on the import path.

# The shared laboratory-model HTTP client, installed ahead of the server package so the
# server's own `laboratory-client` dependency is already satisfied and pip never goes
# looking for it online.
COPY laboratory-client/ /tmp/laboratory-client/
RUN pip install --no-cache-dir /tmp/laboratory-client && rm -rf /tmp/laboratory-client

# This server's own package.
COPY servers/station_server/ /tmp/station_server/
RUN pip install --no-cache-dir /tmp/station_server && rm -rf /tmp/station_server

EXPOSE 50052

# Start the SiLA2 server without TLS for local use; override in compose if needed
CMD ["python", "-m", "station_server", "--ip-address", "0.0.0.0", "--port", "50052", "--insecure"]
