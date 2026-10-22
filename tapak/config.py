"""Application settings (no secrets).

Values come from environment variables with sensible offline defaults. Secret material
(code secret, registry signing key) is referenced by *path* only and lives outside this
config, in the key directory, so the signing key can be held on another machine by a
higher echelon.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


WORKERS_ENV = "TAPAK_WORKERS"
# Most worker processes chosen automatically (without --workers or TAPAK_WORKERS).
AUTO_WORKERS_MAX = 8


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def worker_limit() -> int | None:
    """The cap on worker processes from ``TAPAK_WORKERS``; None when it is unset or empty.

    Raises ValueError (Indonesian) when it holds anything but a positive integer.
    """
    raw = os.environ.get(WORKERS_ENV, "").strip()
    if not raw:
        return None
    if not (raw.isascii() and raw.isdigit()) or int(raw) < 1:
        raise ValueError(f"{WORKERS_ENV} harus bilangan bulat positif (jumlah proses kerja paling banyak), "
                         f"bukan {raw!r}")
    return int(raw)


def available_cpus() -> int:
    """CPUs this process may run on: its affinity mask (``taskset``, ``docker --cpuset-cpus``),
    else ``os.cpu_count()``. A CPU quota (``docker --cpus``) is not visible here: set
    ``TAPAK_WORKERS`` for that."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def pool_size(jobs: int, requested: int | None = None) -> int:
    """Worker processes for ``jobs`` independent jobs.

    ``requested`` (``--workers``) when given, else the available CPUs up to
    :data:`AUTO_WORKERS_MAX`; never more than ``TAPAK_WORKERS`` (ValueError when that is not a
    positive integer) nor more than the jobs, and at least 1.
    """
    limit = worker_limit()
    n = requested if requested else min(available_cpus(), AUTO_WORKERS_MAX)
    if limit is not None:
        n = min(n, limit)
    return max(1, min(n, jobs))


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    Attributes:
        data_dir: workspaces, issued copies and the registry database.
        key_dir: directory of the code secret (operator) and, by default, the signing key.
        signing_key: Ed25519 signing key file; may be absent (rows are then left unsigned
            until the key holder runs ``tapak registry sign``).
        public_key: Ed25519 public key file used to verify the registry.
        canary_domain: zone served by the canary DNS listener.
        llm_provider: "mock" (default, no model needed) or "llamacpp".
        llm_model_path: GGUF model file for the llamacpp provider.
        llm_server_url: local llama.cpp server URL (loopback only).
        anchor_log: external anchor log (``TAPAK_ANCHOR_LOG`` or ``tapak --log-jangkar``),
            an append-only file outside the registry that exposes entries deleted from the
            end of the chain (``tapak.registry.anchor``); None (default) when not used.
    """

    data_dir: Path = field(default_factory=lambda: Path(_env("TAPAK_DATA", "data")))
    key_dir: Path = field(default_factory=lambda: Path(_env("TAPAK_KEY_DIR", "keys")))
    signing_key: Path | None = None
    public_key: Path | None = None
    canary_domain: str = field(default_factory=lambda: _env("TAPAK_CANARY_DOMAIN", "kanari.tapak.test"))
    llm_provider: str = field(default_factory=lambda: _env("TAPAK_LLM", "mock"))
    llm_model_path: str = field(default_factory=lambda: _env("TAPAK_LLM_MODEL", ""))
    llm_server_url: str = field(default_factory=lambda: _env("TAPAK_LLM_URL", "http://127.0.0.1:8080"))
    anchor_log: Path | None = field(default_factory=lambda: _optional_path("TAPAK_ANCHOR_LOG"))

    @property
    def registry_path(self) -> Path:
        """SQLite registry (hash chain, signatures). Canary events live in ``canary_db``."""
        return self.data_dir / "registry.db"

    @property
    def canary_dir(self) -> Path:
        """Folder shared with the internet-facing canary listener (nothing else is mounted there)."""
        return self.data_dir / "kanari"

    @property
    def canary_db(self) -> Path:
        """Canary event log (its own SQLite file, separate from the registry)."""
        return self.canary_dir / "kanari.db"

    @property
    def canary_allow_dir(self) -> Path:
        """Folder the listener may only read (mounted read-only): the token allowlist. It is
        separate from ``canary_dir`` so that nothing the listener can write is ever followed
        or read by the app when it publishes the allowlist."""
        return self.data_dir / "kanari-izin"

    @property
    def canary_allowlist(self) -> Path:
        """SHA-256 digests of issued canary tokens; the listener logs only these."""
        return self.canary_allow_dir / "token_digests.txt"

    @property
    def workspaces(self) -> Path:
        """One folder per issued document."""
        return self.data_dir / "dokumen"

    @property
    def code_secret_path(self) -> Path:
        """Code secret file."""
        return self.key_dir / "code_secret.key"

    @property
    def signing_key_path(self) -> Path:
        """Registry signing key file."""
        return self.signing_key or Path(_env("TAPAK_SIGNING_KEY", str(self.key_dir / "registry_signing.key")))

    @property
    def public_key_path(self) -> Path:
        """Registry public key file."""
        return self.public_key or Path(_env("TAPAK_PUBLIC_KEY", str(self.key_dir / "registry_signing.pub")))


def load_settings() -> Settings:
    """Settings from the environment."""
    return Settings()
