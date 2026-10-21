"""Tardos code generation.

A code for one document consists of a bias vector p (shared by all copies) and one
binary codeword x_j per copy, with x_ji ~ Bernoulli(p_i) independently.

Bias distribution: p_i = sin^2(r_i), r_i uniform on [t', pi/2 - t'] with sin^2(t') = t.
This is the arcsine density f(p) proportional to 1/sqrt(p(1-p)) restricted to [t, 1-t].

Randomness for issued documents comes from SHAKE-256 keyed by the code secret, so a
codeword can be regenerated bit-for-bit years later without depending on the version of
numpy or any other library. Simulations may feed numpy uniforms into the same transforms.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np

from tapak.tardos.params import TardosParams

_STREAM_VERSION = b"TAPAK-stream-v1"
_DIGEST_VERSION = b"TAPAK-code-v1"


def _encode_fields(*fields: bytes) -> bytes:
    """Length-prefix each field so that different field splits never collide."""
    out = bytearray()
    for f in fields:
        out += len(f).to_bytes(4, "big") + f
    return bytes(out)


def uniform_stream(secret: bytes, label: bytes, n: int) -> np.ndarray:
    """Return ``n`` deterministic uniforms in [0, 1) derived from ``secret`` and ``label``.

    Each uniform is the top 53 bits of a little-endian 64-bit word from SHAKE-256 over the
    length-prefixed (version, secret, label). Same inputs always give the same output.
    """
    if n < 0:
        raise ValueError("n tidak boleh negatif")
    xof = hashlib.shake_256(_encode_fields(_STREAM_VERSION, secret, label))
    words = np.frombuffer(xof.digest(8 * n), dtype="<u8")
    return (words >> np.uint64(11)).astype(np.float64) * (1.0 / (1 << 53))


def bias_from_uniform(u: np.ndarray, cutoff: float) -> np.ndarray:
    """Map uniforms in [0, 1) to Tardos biases p in [cutoff, 1 - cutoff] (arcsine density)."""
    if not 0.0 < cutoff < 0.5:
        raise ValueError("batas bias harus di antara 0 dan 0,5")
    t_prime = math.asin(math.sqrt(cutoff))
    r = t_prime + np.asarray(u, dtype=np.float64) * (math.pi / 2.0 - 2.0 * t_prime)
    return np.sin(r) ** 2


def codeword_from_uniform(u: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Draw x_i = 1 if u_i < p_i else 0. Works row-wise for 2-D ``u`` (one row per copy)."""
    return (np.asarray(u) < np.asarray(p)).astype(np.uint8)


def derive_bias(secret: bytes, doc_hash: str, params: TardosParams) -> np.ndarray:
    """Bias vector of the code for document ``doc_hash`` (hex SHA-256 of the master PDF)."""
    u = uniform_stream(secret, b"bias|" + doc_hash.encode(), params.length)
    return bias_from_uniform(u, params.cutoff)


def derive_codeword(secret: bytes, doc_hash: str, copy_id: str, p: np.ndarray) -> np.ndarray:
    """Codeword of copy ``copy_id`` of document ``doc_hash`` given its bias vector ``p``."""
    u = uniform_stream(secret, b"word|" + doc_hash.encode() + b"|" + copy_id.encode(), len(p))
    return codeword_from_uniform(u, p)


def code_digest(doc_hash: str, copy_id: str, codeword: np.ndarray) -> str:
    """Commitment to a codeword, stored in the registry instead of the codeword itself.

    SHA-256 over (version, doc_hash, copy_id, m, packed bits). Revealing the codeword later
    lets a third party check that it was fixed at issuance time.
    """
    x = np.asarray(codeword, dtype=np.uint8)
    if x.ndim != 1 or (x > 1).any():
        raise ValueError("kata kode harus vektor biner 1 dimensi")
    payload = _encode_fields(
        _DIGEST_VERSION,
        doc_hash.encode(),
        copy_id.encode(),
        str(len(x)).encode(),
        np.packbits(x).tobytes(),
    )
    return hashlib.sha256(payload).hexdigest()


def random_code(
    params: TardosParams, n_users: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Fresh (p, X) for simulations, using numpy randomness instead of the keyed stream."""
    m = params.length
    p = bias_from_uniform(rng.random(m), params.cutoff)
    x = codeword_from_uniform(rng.random((n_users, m)), p)
    return p, x
