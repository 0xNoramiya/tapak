"""Ed25519 signing key for registry entries, and the key holder's command line tool.

The private key is a 32-byte seed stored as hex in its own file (default
``keys/registry_signing.key``, mode 0600), never in the application config. The file
holds one line ``ed25519-seed:<64 hex>``; the label makes it impossible to mistake for the
public key file (a bare 64-hex seed written by earlier versions is still read). The
public key is exported as bare hex next to it (``keys/registry_signing.pub``) and is all
a verifier needs.

What gets signed: the 32 raw bytes of an entry's ``entry_hash`` (the SHA-256 digest, not
its hex text). Signatures and public keys are stored as lowercase hex.

The key can live with a higher echelon on another machine: TAPAK then appends entries
unsigned and the key holder reviews and signs them later::

    python -m tapak.registry.signing generate --key keys/registry_signing.key
    python -m tapak.registry.signing sign-pending data/registry.db --daftar
    python -m tapak.registry.signing sign-pending data/registry.db --key keys/registry_signing.key --sampai 42

``--daftar`` lists the unsigned entries (number, kind, doc_hash, recipient_id, copy_id);
``--sampai N`` signs them up to entry N only, so an entry slipped in after the review
stays unsigned.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

from tapak.keys import DEFAULT_KEY_DIR

if TYPE_CHECKING:
    from tapak.registry.chain import Registry

SIGNING_KEY_FILE = "registry_signing.key"
PUBLIC_KEY_FILE = "registry_signing.pub"
SEED_PREFIX = "ed25519-seed:"
PRIVATE_SUFFIX = ".key"
PUBLIC_SUFFIX = ".pub"
_MAX_KEY_FILE = 4096  # bytes; a key file is one short line
_HEX = frozenset("0123456789abcdef")


class SigningKeyError(ValueError):
    """Raised for a missing, malformed, misused or already existing key file."""


def default_signing_key_path(key_dir: Path | None = None) -> Path:
    """Location of the private signing key file."""
    return Path(key_dir or DEFAULT_KEY_DIR) / SIGNING_KEY_FILE


def default_public_key_path(key_dir: Path | None = None) -> Path:
    """Location of the exported public key file."""
    return Path(key_dir or DEFAULT_KEY_DIR) / PUBLIC_KEY_FILE


def _is_hex(text: str, n_chars: int) -> bool:
    return len(text) == n_chars and set(text) <= _HEX


class Signer:
    """An Ed25519 private key that signs registry entry hashes."""

    def __init__(self, seed: bytes) -> None:
        if len(seed) != 32:
            raise SigningKeyError("benih kunci penanda tangan harus 32 byte")
        self._key = SigningKey(seed)

    @classmethod
    def generate(cls) -> "Signer":
        """A fresh random key (from the operating system's CSPRNG)."""
        return cls(bytes(SigningKey.generate()))

    @property
    def public_key_hex(self) -> str:
        """Public key as 64 lowercase hex characters."""
        return bytes(self._key.verify_key).hex()

    def seed_hex(self) -> str:
        """Private seed as hex (only for writing the key file)."""
        return bytes(self._key).hex()

    def sign(self, message: bytes) -> str:
        """Detached Ed25519 signature of ``message`` as 128 hex characters."""
        return self._key.sign(message).signature.hex()

    def __repr__(self) -> str:  # never print the seed
        return f"Signer(public_key={self.public_key_hex[:16]}...)"


def _write_new_file(path: Path, text: str, mode: int, overwrite: bool) -> None:
    """Write ``text`` with permissions ``mode`` set before any byte is written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    try:
        fd = os.open(path, flags, mode)
    except FileExistsError:
        raise SigningKeyError(f"berkas kunci sudah ada, tidak ditimpa: {path}") from None
    try:
        os.fchmod(fd, mode)  # also when the file existed (overwrite) or umask interfered
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(text)


def _same_file(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve()


def export_public_key(signer: Signer, path: Path | None = None) -> Path:
    """Write the public key as hex (one line) and return the path."""
    path = Path(path) if path else default_public_key_path()
    if path.suffix.lower() == PRIVATE_SUFFIX:
        raise SigningKeyError(f"kunci publik tidak boleh ditulis ke berkas berakhiran .key: {path}")
    _write_new_file(path, signer.public_key_hex + "\n", 0o644, overwrite=True)
    return path


def generate_signing_key(
    path: Path | None = None, public_path: Path | None = None, overwrite: bool = False
) -> Signer:
    """Create a new key file (mode 0600) and export its public key.

    ``public_path`` defaults to the key path with suffix ``.pub``. An existing key file is
    never replaced unless ``overwrite`` is set. Refuses a key path ending in ``.pub`` and a
    public path equal to the key path, either of which would overwrite the seed.
    """
    path = Path(path) if path else default_signing_key_path()
    public_path = Path(public_path) if public_path else path.with_suffix(PUBLIC_SUFFIX)
    if path.suffix.lower() == PUBLIC_SUFFIX:
        raise SigningKeyError(f"berkas kunci privat tidak boleh berakhiran .pub: {path}")
    if _same_file(path, public_path):
        raise SigningKeyError("berkas kunci publik harus berbeda dari berkas kunci privat")
    signer = Signer.generate()
    _write_new_file(path, f"{SEED_PREFIX}{signer.seed_hex()}\n", 0o600, overwrite=overwrite)
    export_public_key(signer, public_path)
    return signer


def _read_key_file(path: Path) -> str:
    """Contents of a small ASCII key file, stripped and lowercased."""
    with open(path, "rb") as fh:
        raw = fh.read(_MAX_KEY_FILE + 1)
    if len(raw) > _MAX_KEY_FILE:
        raise SigningKeyError(f"berkas kunci terlalu besar: {path}")
    try:
        return raw.decode("ascii").strip().lower()
    except UnicodeDecodeError:
        raise SigningKeyError(f"berkas kunci berisi karakter yang tidak sah: {path}") from None


def load_signer(path: Path | None = None, create: bool = False) -> Signer:
    """Read the signing key file (``ed25519-seed:<hex>`` or bare hex); optionally create it."""
    path = Path(path) if path else default_signing_key_path()
    if not path.exists():
        if not create:
            raise FileNotFoundError(f"kunci penanda tangan registri tidak ditemukan: {path}")
        return generate_signing_key(path)
    text = _read_key_file(path).removeprefix(SEED_PREFIX)
    if not _is_hex(text, 64):
        raise SigningKeyError(f"kunci penanda tangan harus berisi 64 karakter heksadesimal: {path}")
    return Signer(bytes.fromhex(text))


def normalize_public_key(public_key_hex: str) -> str:
    """Validate a hex public key (64 hex characters) and return it in lowercase."""
    text = public_key_hex.strip().lower()
    if text.startswith(SEED_PREFIX):
        raise SigningKeyError("itu kunci PRIVAT, bukan kunci publik; gunakan isi berkas .pub")
    if not _is_hex(text, 64):
        raise SigningKeyError("kunci publik harus 64 karakter heksadesimal")
    return text


def load_public_key(value: str | Path) -> str:
    """Public key from a hex string or from the path of a ``.pub`` file.

    Refuses the private key file (suffix ``.key``, the default key location, or contents
    labelled ``ed25519-seed:``) so the seed can never end up printed in a report.
    """
    path = Path(value)
    if path.is_file():
        if path.suffix.lower() == PRIVATE_SUFFIX or _same_file(path, default_signing_key_path()):
            raise SigningKeyError(f"itu berkas kunci PRIVAT, gunakan berkas .pub: {path}")
        return normalize_public_key(_read_key_file(path))
    text = str(value).strip().lower()
    if _is_hex(text, 64) or text.startswith(SEED_PREFIX):
        return normalize_public_key(text)
    raise SigningKeyError(f"kunci publik bukan heksadesimal yang sah dan bukan berkas: {value}")


def verify_signature(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    """True if ``signature_hex`` is a valid Ed25519 signature of ``message``."""
    try:
        sig = bytes.fromhex(signature_hex)
        key = VerifyKey(bytes.fromhex(public_key_hex))
        key.verify(message, sig)
    except (BadSignatureError, ValueError, TypeError):
        return False
    return True


# ---- command line helpers shared by the registry tools ---------------------------------

# argparse error messages (Python 3.12) and their Indonesian rendering.
_ARG_ERRORS = [
    (re.compile(r"the following arguments are required: (.+)"), "argumen wajib belum diisi: {0}"),
    (re.compile(r"unrecognized arguments: (.+)"), "argumen tidak dikenal: {0}"),
    (re.compile(r"argument (.+?): expected one argument"), "argumen {0} membutuhkan satu nilai"),
    (re.compile(r"argument (.+?): invalid choice: (.+?) \(choose from (.+)\)"),
     "pilihan {1} tidak sah untuk {0} (pilihan: {2})"),
    (re.compile(r"argument (.+?): invalid \w+ value: (.+)"), "nilai {1} tidak sah untuk {0}"),
    (re.compile(r"argument (.+?): not allowed with argument (.+)"), "argumen {0} tidak boleh dipakai bersama {1}"),
    (re.compile(r"ambiguous option: (\S+)"), "opsi {0} ambigu"),
]


class _IndonesianHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[no-untyped-def]
        super().add_usage(usage, actions, groups, "Penggunaan: " if prefix is None else prefix)


class IndonesianArgumentParser(argparse.ArgumentParser):
    """ArgumentParser with Indonesian help and errors; a usage error exits with code 1.

    The registry tools promise exit code 0 (success) or 1 (anything else), so argparse's
    usual exit code 2 and English messages are replaced.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("formatter_class", _IndonesianHelpFormatter)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._positionals.title = "argumen posisi"
        self._optionals.title = "opsi"
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS,
                          help="tampilkan bantuan ini lalu keluar")

    def error(self, message: str) -> NoReturn:
        """Print an Indonesian usage error and exit with code 1."""
        text = "argumen perintah tidak sah"
        for pattern, template in _ARG_ERRORS:
            m = pattern.fullmatch(message)
            if m:
                text = template.format(*m.groups())
                break
        self.print_usage(sys.stderr)
        print(f"Gagal: {text} (lihat --help)", file=sys.stderr)
        raise SystemExit(1)


def describe_error(exc: BaseException) -> str:
    """Indonesian description of an error for command line output (never a traceback)."""
    name = getattr(exc, "filename", None)
    if isinstance(exc, FileNotFoundError) and name:
        return f"berkas tidak ditemukan: {name}"
    if isinstance(exc, IsADirectoryError) and name:
        return f"yang diberikan adalah folder, bukan berkas: {name}"
    if isinstance(exc, PermissionError) and name:
        return f"tidak ada izin mengakses berkas: {name}"
    if isinstance(exc, sqlite3.Error):
        return "registri tidak dapat dibuka atau ditulis (bukan berkas SQLite, rusak, atau sedang terkunci)"
    if isinstance(exc, UnicodeError):
        return "berkas berisi karakter yang tidak sah"
    if isinstance(exc, OSError) and not isinstance(exc, FileNotFoundError):
        return f"kesalahan berkas: {name or exc.strerror or 'tidak diketahui'}"
    return str(exc)


# ---- key holder's tool ------------------------------------------------------------------


def _print_pending(reg: Registry) -> None:
    """Print the last signed entry number and every unsigned entry of ``reg``."""
    from tapak.registry.chain import describe_entry

    pending = reg.pending()
    last = reg.last_signed_seq()
    print("Entri bertanda tangan terakhir: " + (f"#{last}" if last else "belum ada"))
    print(f"Entri belum bertanda tangan: {len(pending)}")
    for e in pending:
        print("  " + describe_entry(e))


def main(argv: list[str] | None = None) -> int:
    """Key holder's tool: ``generate`` a key or review and ``sign-pending`` entries."""
    ap = IndonesianArgumentParser(prog="python -m tapak.registry.signing",
                                  description="Kunci tanda tangan registri TAPAK.")
    sub = ap.add_subparsers(dest="cmd", required=True, title="perintah")
    g = sub.add_parser("generate", help="buat kunci penanda tangan baru")
    g.add_argument("--key", default=None, help="berkas kunci privat (bawaan keys/registry_signing.key)")
    g.add_argument("--public", default=None, help="berkas kunci publik (bawaan: sama dengan --key, akhiran .pub)")
    g.add_argument("--overwrite", action="store_true", help="timpa kunci yang sudah ada")
    s = sub.add_parser("sign-pending", help="periksa lalu tanda tangani entri registri yang belum bertanda tangan")
    s.add_argument("registry", help="berkas registri SQLite")
    s.add_argument("--key", default=None, help="berkas kunci privat (bawaan keys/registry_signing.key)")
    s.add_argument("--daftar", action="store_true",
                   help="hanya tampilkan entri yang belum bertanda tangan, tanpa menandatangani")
    s.add_argument("--sampai", type=int, default=None, metavar="NOMOR",
                   help="tanda tangani entri sampai nomor ini (entri terakhir yang sudah Anda periksa)")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "generate":
            key_path = Path(args.key) if args.key else default_signing_key_path()
            pub_path = Path(args.public) if args.public else key_path.with_suffix(PUBLIC_SUFFIX)
            signer = generate_signing_key(key_path, pub_path, overwrite=args.overwrite)
            print(f"Kunci privat ditulis ke {key_path} (mode 0600). Simpan terpisah dari konfigurasi.")
            print(f"Kunci publik ditulis ke {pub_path}: {signer.public_key_hex}")
            return 0
        from tapak.registry.chain import Registry, describe_entry, sign_pending

        if not Path(args.registry).is_file():
            raise SigningKeyError(f"berkas registri tidak ditemukan: {args.registry}")
        if args.daftar or args.sampai is None:
            with Registry.open(args.registry) as reg:
                _print_pending(reg)
            if args.daftar:
                return 0
            print("Tidak ada yang ditandatangani. Periksa daftar di atas, lalu jalankan lagi dengan "
                  "--sampai NOMOR (entri terakhir yang sudah Anda periksa).", file=sys.stderr)
            return 1
        signer = load_signer(Path(args.key) if args.key else None)
        with Registry.open(args.registry) as reg:
            todo = [e for e in reg.pending() if e.seq <= args.sampai]
            n = sign_pending(reg, signer, up_to=args.sampai)
            rest = [e.seq for e in reg.pending()]
        print(f"{n} entri sampai #{args.sampai} ditandatangani dengan kunci {signer.public_key_hex[:16]}...")
        for e in todo:
            print("  " + describe_entry(e))
        if rest:
            span = f"#{rest[0]}" if len(rest) == 1 else f"#{rest[0]}..#{rest[-1]}"
            print(f"{len(rest)} entri sesudahnya ({span}) belum diperiksa dan belum bertanda tangan.")
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"Gagal: {describe_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
