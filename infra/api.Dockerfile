FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY libs/core libs/core
COPY apps/api apps/api
RUN pip install ./libs/core ./apps/api
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
