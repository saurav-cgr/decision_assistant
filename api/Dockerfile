FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    DOCLING_ARTIFACTS_PATH=/opt/docling-models

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgl1 tesseract-ocr tesseract-ocr-eng \
       curl gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pg_dump must match compose.yaml's pinned `pgvector/pgvector:pg16` server exactly: Debian's own
# repo only offers the latest default major version (v17 on trixie), and a v17 dump embeds syntax
# (e.g. `SET transaction_timeout = 0;`) a v16 server's psql rejects on restore. PGDG is the
# official PostgreSQL apt repository (same publisher as the pgvector image already pulled),
# fetched at build time only, never at runtime.
RUN install -d /usr/share/postgresql-common/pgdg \
    && curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
       https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list' \
    && apt-get update \
    && apt-get install --yes --no-install-recommends postgresql-client-16 \
    && apt-get purge --yes curl gnupg \
    && apt-get autoremove --yes \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/api

# Dependencies, tokenizer cache, and Docling models are keyed on pyproject.toml alone so that
# source-only edits reuse this layer instead of reinstalling everything and redownloading models.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
       > /tmp/requirements.txt \
    && pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
    && docling-tools models download layout tableformer --output-dir "$DOCLING_ARTIFACTS_PATH" \
    && tesseract --list-langs | grep --line-regexp eng \
    && test -d "$DOCLING_ARTIFACTS_PATH/docling-project--docling-layout-heron" \
    && test -d "$DOCLING_ARTIFACTS_PATH/docling-project--docling-models"

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN pip install --no-cache-dir --no-deps '.'

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

CMD ["uvicorn", "decision_assistant.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM base AS test

RUN pip install --no-cache-dir '.[dev]'
COPY tests ./tests
