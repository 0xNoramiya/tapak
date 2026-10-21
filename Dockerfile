# TAPAK: one image, two services (web app and canary DNS listener).
# Building needs network access once; the running containers need none.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-ind poppler-utils \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin tapak

WORKDIR /app
COPY pyproject.toml README.md ./
COPY tapak ./tapak
COPY samples ./samples
RUN pip install --no-cache-dir . && mkdir -p /data /keys && chown tapak:tapak /data /keys

ENV TAPAK_DATA=/data \
    TAPAK_KEY_DIR=/keys \
    TAPAK_ALLOWED_HOSTS=127.0.0.1,localhost \
    PYTHONUNBUFFERED=1
USER tapak
EXPOSE 8000
CMD ["uvicorn", "tapak.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
