# TAPAK: one image, two services (web app and canary DNS listener).
# Building needs network access once; the running containers need none.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-ind poppler-utils \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY tapak ./tapak
COPY samples ./samples
RUN pip install --no-cache-dir .

ENV TAPAK_DATA=/data \
    TAPAK_KEY_DIR=/keys \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "tapak.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
