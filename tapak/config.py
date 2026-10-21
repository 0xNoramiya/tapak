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


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


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
    """

    data_dir: Path = field(default_factory=lambda: Path(_env("TAPAK_DATA", "data")))
    key_dir: Path = field(default_factory=lambda: Path(_env("TAPAK_KEY_DIR", "keys")))
    signing_key: Path | None = None
    public_key: Path | None = None
    canary_domain: str = field(default_factory=lambda: _env("TAPAK_CANARY_DOMAIN", "kanari.tapak.test"))
    llm_provider: str = field(default_factory=lambda: _env("TAPAK_LLM", "mock"))
    llm_model_path: str = field(default_factory=lambda: _env("TAPAK_LLM_MODEL", ""))
    llm_server_url: str = field(default_factory=lambda: _env("TAPAK_LLM_URL", "http://127.0.0.1:8080/completion"))

    @property
    def registry_path(self) -> Path:
        """SQLite registry (hash chain, signatures, canary events)."""
        return self.data_dir / "registry.db"

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
