FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m pip install --no-cache-dir \
      chromadb==1.0.15 \
      qdrant-client==1.15.1

COPY recipes/ /opt/techscout/recipes/

RUN useradd --system --uid 65532 --no-create-home sandbox \
    && chmod -R a=rX /opt/techscout

USER 65532:65532
WORKDIR /workspace
