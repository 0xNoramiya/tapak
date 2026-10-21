"""Secret material, kept outside the application config.

* Code secret (32 random bytes): derives every bias vector, codeword and embedding plan.
  Whoever holds it can regenerate codewords, so it stays with the TAPAK operator.
* Ed25519 signing key (see ``registry/signing.py``): signs registry rows and can be held
  by a higher echelon on a separate machine; TAPAK then only needs the public key.

Both live in files given by path (default ``keys/``, which is git-ignored). Files are
written with mode 0600.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

DEFAULT_KEY_DIR = Path(os.environ.get("TAPAK_KEY_DIR", "keys"))
CODE_SECRET_FILE = "code_secret.key"


def _write_private(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(data)


def code_secret_path(key_dir: Path | None = None) -> Path:
    """Location of the code secret file."""
    return Path(key_dir or DEFAULT_KEY_DIR) / CODE_SECRET_FILE


def load_code_secret(path: Path | None = None, create: bool = False) -> bytes:
    """Read the 32-byte code secret (hex file); optionally create it if missing."""
    path = Path(path) if path else code_secret_path()
    if not path.exists():
        if not create:
            raise FileNotFoundError(f"rahasia kode tidak ditemukan: {path}")
        _write_private(path, secrets.token_hex(32) + "\n")
    raw = bytes.fromhex(path.read_text(encoding="ascii").strip())
    if len(raw) != 32:
        raise ValueError(f"rahasia kode harus 32 byte: {path}")
    return raw
