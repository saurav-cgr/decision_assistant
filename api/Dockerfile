FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    DOCLING_ARTIFACTS_PATH=/opt/docling-models

RUN apt-get update \
    && apt-get install --yes --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/api

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir --editable '.[dev]' \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
    && docling-tools models download layout tableformer --output-dir "$DOCLING_ARTIFACTS_PATH" \
    && tesseract --list-langs | grep --line-regexp eng \
    && test -d "$DOCLING_ARTIFACTS_PATH/docling-project--docling-layout-heron" \
    && test -d "$DOCLING_ARTIFACTS_PATH/docling-project--docling-models"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

CMD ["uvicorn", "decision_assistant.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
