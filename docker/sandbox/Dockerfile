# syntax=docker/dockerfile:1.7

FROM python:3.11.9-slim-bookworm AS sandbox-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY recipes/ /opt/techscout/recipes/
COPY ci_smoke.py /opt/techscout/ci_smoke.py

RUN useradd --system --uid 65532 --no-create-home sandbox \
    && chmod -R a=rX /opt/techscout

USER 65532:65532
WORKDIR /workspace

# The fast CI target deliberately excludes the heavyweight candidate packages.
# It verifies that the common runtime can build and obey the container boundary.
FROM sandbox-runtime AS ci-smoke

CMD ["python", "/opt/techscout/ci_smoke.py"]

# Keep the default image compatible with the reviewed Wave 1 recipes. BuildKit's
# cache avoids repeatedly downloading the pinned wheels during local rebuilds.
FROM sandbox-runtime AS recipe-runtime

USER root
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install \
      --timeout 30 \
      --retries 2 \
      chromadb==1.0.15 \
      qdrant-client==1.15.1

USER 65532:65532
