"""Secret material, kept outside the application config.

* Code secret (32 random bytes): derives every bias vector, codeword and embedding plan.
  Whoever holds it can regenerate codewords, so it stays with the TAPAK operator.
* Ed25519 signing key (see ``registry/signing.py``): signs registry rows and can be held
  by a higher echelon on a separate machine; TAPAK then only needs the public key.

Both live in files given by path (default ``keys/``, which is git-ignored). Files are
written with mode 0600.

Research seed (``tapak issue --benih-riset``): the README photo benchmark (``make photos``,
``make photos-cetak``, ``make bench``) must be reproducible byte for byte, so its issuance
derives the code secret and the copy ids from a public seed instead of drawing them. Anyone
who knows the seed can regenerate every codeword of that issuance and frame any of its
recipients, so a seeded issuance is for research only and never for a real document: the
CLI refuses it unless the registry is left out, and never replaces an existing secret.
"""

from __future__ import annotations

import hashlib
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


# Domain label of every value derived from a research seed (changing it changes every value).
RESEARCH_SEED_DOMAIN = "TAPAK benih riset v1"


def _check_research_seed(seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("benih riset harus bilangan bulat tidak negatif")


def research_code_secret(seed: int) -> bytes:
    """The 32-byte code secret of a research seed: SHA-256 of the domain label and the seed.

    Research only (benchmarks): the seed is public, so this secret protects nothing.
    """
    _check_research_seed(seed)
    return hashlib.sha256(f"{RESEARCH_SEED_DOMAIN}: rahasia kode {seed}".encode("ascii")).digest()


def research_copy_ids(seed: int, n: int) -> list[str]:
    """Copy ids of copies 1 to n of a research issuance (16 hex characters, like a drawn id).

    Copy i gets the first 16 hex characters of SHA-256 of the domain label, the seed and i, so
    the ids do not depend on the code secret and a longer roster keeps the first ids.
    """
    _check_research_seed(seed)
    return [hashlib.sha256(f"{RESEARCH_SEED_DOMAIN}: id salinan {seed} {i}".encode("ascii")).hexdigest()[:16]
            for i in range(1, n + 1)]


def research_marker_path(secret_path: Path) -> Path:
    """Marker next to a code secret that came from a research seed (``code_secret.riset``)."""
    return Path(secret_path).with_suffix(".riset")


def research_seed_of(secret_path: Path) -> int | None:
    """The research seed the code secret at ``secret_path`` was derived from, or None.

    Read from the marker that ``install_research_secret`` writes; a secret drawn by
    ``load_code_secret`` or ``tapak keys init`` has none.
    """
    marker = research_marker_path(secret_path)
    if not marker.exists():
        return None
    first = marker.read_text(encoding="ascii").split()
    return int(first[0]) if first and first[0].isdigit() else -1  # -1: marker damaged, still research


def install_research_secret(path: Path, seed: int) -> bytes:
    """Write the research seed's code secret to ``path`` (mode 0600) unless it is already there.

    A key file that holds any other secret is refused (ValueError) and left untouched: a real
    code secret is never replaced, and a research issuance never runs under a real secret. The
    marker ``code_secret.riset`` (``research_seed_of``) is written before the secret, so a
    research secret never sits in a key folder without it; ordinary issuance refuses a key
    folder with that marker (``tapak.service.issue_document``).
    """
    want = research_code_secret(seed)
    path = Path(path)
    if path.exists() and load_code_secret(path) != want:
        raise ValueError(f"folder kunci sudah berisi rahasia kode lain ({path}); benih riset tidak pernah "
                         "menimpanya. Pakai folder kunci tersendiri untuk penerbitan riset")
    _write_private(research_marker_path(path),
                   f"{seed}\nrahasia kode di folder ini diturunkan dari benih riset {seed} yang publik; "
                   "hanya untuk riset, jangan untuk dokumen sungguhan\n")
    if not path.exists():
        _write_private(path, want.hex() + "\n")
    return want
