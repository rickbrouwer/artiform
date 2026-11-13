FROM python:3.15-slim

LABEL org.opencontainers.image.title="ArtiForm"
LABEL org.opencontainers.image.description="Config-as-code for JFrog Artifactory"
LABEL org.opencontainers.image.source="https://github.com/rickbrouwer/artiform"

# Install artiform from this repo. Install setuptools explicitly and build
# without isolation: this is the same install path air-gapped operators use
# (no index access for the build backend), so the public image build keeps
# exercising it.
COPY pyproject.toml README.md /build/
COPY artiform/ /build/artiform/
RUN python3 -m pip install --no-cache-dir setuptools wheel && \
    python3 -m pip install --no-cache-dir --no-build-isolation /build && \
    rm -rf /build
