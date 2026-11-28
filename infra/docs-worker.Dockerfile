# Documents worker (`docs` queue, PROJECT_PLAN 3.9): accessible PDF generation + the veraPDF gate.
# Proven in the PDF/UA spike (ADR 0008): renders the Tamil/Devanagari stress report and passes PDF/UA-1.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 A11Y_RULES_DIR=/app/rules
# Pango for WeasyPrint; Noto fonts so Indian scripts render with real glyphs, not boxes; a JRE for veraPDF.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-core fonts-noto-ui-core default-jre-headless \
 && rm -rf /var/lib/apt/lists/*
# veraPDF is plain Java; copy it from the official image (pin by digest before production).
COPY --from=ghcr.io/verapdf/cli /opt/verapdf /opt/verapdf
ENV VERAPDF_BIN=/opt/verapdf/verapdf
WORKDIR /app
COPY libs/core libs/core
COPY workers/documents workers/documents
COPY rules rules
RUN pip install ./libs/core ./workers/documents
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
CMD ["celery", "-A", "a11y_core.celery_app", "worker", "-Q", "docs", "--concurrency=2", "--loglevel=INFO"]
