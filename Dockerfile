# check=skip=SecretsUsedInArgOrEnv
# (TAPAK_KEY_DIR below is a folder path, not a secret.)
#
# TAPAK: one image, two services (web app and canary DNS listener).
# XDG_CACHE_HOME gives fontconfig (used by WeasyPrint for the berita acara) a writable cache
# for the unprivileged user.
# Building needs network access once; the running containers need none. OTEL_SDK_DISABLED
# keeps the OpenTelemetry hooks that recent FastAPI versions ship switched off for good.
# The Debian release is pinned (trixie: Tesseract 5.5.0): scanned masters must be traced with
# the same Tesseract that found their word boxes at issuance, and a rebuild on a newer release
# would bring another version (docs/operasi.md, Docker).
FROM python:3.12-slim-trixie

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
    XDG_CACHE_HOME=/tmp/cache \
    OTEL_SDK_DISABLED=true \
    PYTHONUNBUFFERED=1
USER tapak
EXPOSE 8000
CMD ["uvicorn", "tapak.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
