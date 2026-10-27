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
# Python libraries come from requirements.lock: exactly the versions of the tested virtualenv
# (scripts/kunci_versi.py), wheels only, nothing resolved at build time; pip check fails the
# build if the lock misses a dependency. Refresh it with make kunci-versi.
# TAPAK_WORKERS (docker-compose.yml) caps the worker processes: os.cpu_count() in a container
# counts every CPU of the host.
FROM python:3.12-slim-trixie AS tapak

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-ind poppler-utils \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin tapak

WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.lock ./
RUN pip install --no-cache-dir --no-deps --only-binary :all: -r requirements.lock
COPY pyproject.toml README.md ./
COPY tapak ./tapak
COPY samples ./samples
RUN pip install --no-cache-dir --no-deps . && pip check && mkdir -p /data /keys && chown tapak:tapak /data /keys

ENV TAPAK_DATA=/data \
    TAPAK_KEY_DIR=/keys \
    TAPAK_ALLOWED_HOSTS=127.0.0.1,localhost \
    XDG_CACHE_HOME=/tmp/cache \
    OTEL_SDK_DISABLED=true \
    PYTHONUNBUFFERED=1
USER tapak
EXPOSE 8000
CMD ["uvicorn", "tapak.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

# Fly.io (fly.toml builds this target): starts as root only to hand the volume at /data to the
# user tapak, then runs the web app and the canary listener as tapak (scripts/fly_mulai.sh).
FROM tapak AS fly
USER root
COPY --chmod=0755 scripts/fly_mulai.sh /usr/local/bin/tapak-fly
CMD ["/usr/local/bin/tapak-fly"]

# The default target (docker build, docker compose) is the image above, unchanged.
FROM tapak
