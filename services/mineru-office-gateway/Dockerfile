FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/office-home

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation2 \
        fonts-noto-core \
        fonts-noto-cjk \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 office \
    && mkdir -p /app /tmp/mineru-office /tmp/office-home \
    && chown -R office:office /app /tmp/mineru-office /tmp/office-home

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY --chown=office:office app /app/app
COPY --chown=office:office entrypoint.sh /app/entrypoint.sh
RUN chmod 0755 /app/entrypoint.sh

USER office
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8081/health || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
