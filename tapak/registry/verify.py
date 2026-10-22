"""Independent verification of a registry file with nothing but the public key.

``verify_registry`` reads the SQLite file read-only and, for every entry in ``seq`` order,
checks:

1. ``seq`` runs 1, 2, 3, ... without gaps;
2. the payload is canonical JSON and ``entry_hash`` equals the SHA-256 of the hashed
   fields (seq, kind, payload, prev_hash, created_at);
3. ``prev_hash`` equals the previous entry's ``entry_hash`` (64 zeros for the first);
4. ``created_at`` is a valid timestamp and never goes back in time;
5. a signed entry was signed by the given public key, and the Ed25519 signature over the
   32 bytes of ``entry_hash`` is valid;
6. signed entries form a prefix (an unsigned entry before a signed one means a signature
   was removed);
7. by default every entry is signed: an unsigned entry is protected by nothing but the
   hash chain, which anyone with write access can recompute. ``require_signed=False``
   (``--izinkan-belum-bertanda-tangan``) accepts unsigned entries for the deferred
   signing workflow, and the verdict then names them;
8. an empty registry is a problem (nothing to verify, or every entry deleted);
9. every ``trace`` entry is valid (fields, hashes, eps share on the schedule
   eps * 6 / (pi^2 k^2), and for a staged trace a known stage policy whose stage eps are
   that policy's split of the share), follows the ``document`` entry of its document with the same eps,
   and its number continues that document's count (1, 2, 3, ...): a duplicate or skipped
   number means the trace log was not written by TAPAK;
10. a ``document`` entry with lexical fields (word-choice channel) has all of them, with
    valid digests, a known position rule and position lists only.

What a hash chain cannot show by itself is entries deleted from the *end*: a shorter
chain is still a valid chain. That needs a value kept outside the file: a recorded
``(seq, entry_hash)`` anchor (``--jangkar``) or the exported daily Merkle root files
(``--merkle-dir``). The report prints the current head as an anchor to write down.

The triggers are compared with the expected SQL text; a missing or altered trigger is a
warning (it shows the file was edited outside TAPAK), not proof of tampering.

It needs no TAPAK configuration and no secret: anyone holding the file and the public key
can run ``tapak-verify-registry data/registry.db --public-key keys/registry_signing.pub``.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tapak.registry.chain import (
    KIND_DOCUMENT,
    KIND_LABELS,
    KIND_TRACE,
    LEXICAL_DOCUMENT_FIELDS,
    ZERO_HASH,
    entry_content_problems,
    lexical_document_problems,
    parse_time,
    trace_payload_problems,
    trigger_problems,
)
from tapak.registry.merkle import check_daily_roots
from tapak.registry.signing import (
    IndonesianArgumentParser,
    describe_error,
    load_public_key,
    normalize_public_key,
    verify_signature,
)

_ANCHOR = re.compile(r"([0-9]+):([0-9a-f]{64})")


def _span(first: int, last: int) -> str:
    return f"#{first}" if first == last else f"#{first}..#{last}"


@dataclass
class VerifyReport:
    """Outcome of :func:`verify_registry`.

    Attributes:
        problems: (seq, description in Indonesian). seq 0 means the problem concerns the
            file or an exported root file rather than one entry.
        warnings: facts worth knowing that do not by themselves prove tampering.
        unsigned_first, unsigned_last: range of the unsigned entries, if any.
        merkle_files, anchors_checked: None when that check was not requested.
        traces: number of ``trace`` entries per document hash.
    """

    db_path: str
    public_key: str
    require_signed: bool = True
    entries: int = 0
    unsigned: int = 0
    unsigned_first: int | None = None
    unsigned_last: int | None = None
    problems: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    kinds: dict[str, int] = field(default_factory=dict)
    head_seq: int | None = None
    head_hash: str | None = None
    merkle_files: int | None = None
    anchors_checked: int | None = None
    traces: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True if no problem was found."""
        return not self.problems

    @property
    def fully_signed(self) -> bool:
        """True if the registry has entries and every one of them is signed."""
        return self.entries > 0 and self.unsigned == 0

    def verdict(self) -> str:
        """Final line of the report (Indonesian)."""
        if self.problems:
            return f"HASIL: TIDAK UTUH, ditemukan {len(self.problems)} masalah"
        if self.unsigned and self.unsigned_first is not None and self.unsigned_last is not None:
            return (f"HASIL: RANTAI UTUH, TETAPI {self.unsigned} entri ({_span(self.unsigned_first, self.unsigned_last)}) "
                    "belum bertanda tangan dan tidak terlindungi dari pemalsuan")
        return f"HASIL: UTUH, rantai hash dan semua tanda tangan sah untuk entri #1..#{self.head_seq}"

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly form."""
        return {"ok": self.ok, "fully_signed": self.fully_signed, "verdict": self.verdict(),
                "db_path": self.db_path, "public_key": self.public_key, "require_signed": self.require_signed,
                "entries": self.entries, "unsigned": self.unsigned, "unsigned_first": self.unsigned_first,
                "unsigned_last": self.unsigned_last, "problems": [list(p) for p in self.problems],
                "warnings": list(self.warnings), "kinds": dict(self.kinds), "head_seq": self.head_seq,
                "head_hash": self.head_hash, "merkle_files": self.merkle_files,
                "anchors_checked": self.anchors_checked, "traces": dict(self.traces)}

    def lines(self) -> list[str]:
        """Human-readable report in Indonesian."""
        kinds = ", ".join(f"{KIND_LABELS.get(k, k)} {n}" for k, n in sorted(self.kinds.items()))
        out = [
            "Verifikasi registri TAPAK",
            f"  Berkas           : {self.db_path}",
            f"  Kunci publik     : {self.public_key}",
            f"  Jumlah entri     : {self.entries}" + (f" ({kinds})" if kinds else ""),
            f"  Bertanda tangan  : {self.entries - self.unsigned}, belum: {self.unsigned}",
        ]
        if self.traces:
            out.append(f"  Pelacakan        : {sum(self.traces.values())} untuk {len(self.traces)} dokumen "
                       f"(terbanyak {max(self.traces.values())} untuk satu dokumen)")
        if self.head_seq is not None:
            out.append(f"  Ujung rantai     : entri #{self.head_seq}, hash {self.head_hash}")
            out.append(f"                     (catat di luar sistem; periksa lagi nanti dengan "
                       f"--jangkar {self.head_seq}:{self.head_hash})")
        if self.merkle_files is not None:
            out.append(f"  Akar Merkle      : {self.merkle_files} berkas harian dicocokkan")
        if self.anchors_checked is not None:
            out.append(f"  Jangkar          : {self.anchors_checked} dicocokkan")
        out.extend(f"Peringatan: {w}" for w in self.warnings)
        if self.problems:
            out.append(f"Masalah ({len(self.problems)}):")
            for seq, text in self.problems:
                where = f"entri #{seq}" if seq else "berkas"
                out.append(f"  {where}: {text}")
        if self.merkle_files is None and self.anchors_checked is None:
            out.append("Catatan: tanpa --jangkar atau --merkle-dir, entri yang dihapus dari ujung rantai "
                       "tidak dapat dideteksi.")
        out.append(self.verdict())
        return out


def parse_anchor(text: str) -> tuple[int, str]:
    """Parse an anchor ``SEQ:HASH`` (entry number and its 64-hex ``entry_hash``)."""
    m = _ANCHOR.fullmatch(text.strip().lower())
    if not m or int(m.group(1)) < 1:
        raise ValueError(f"jangkar harus berbentuk NOMOR:HASH (hash 64 karakter heksadesimal): {text}")
    return int(m.group(1)), m.group(2)


def _read_rows(db_path: Path) -> tuple[list[tuple[Any, ...]], list[str]]:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT seq, kind, payload, prev_hash, created_at, entry_hash, signature, signer "
            "FROM entries ORDER BY seq").fetchall()
        triggers = trigger_problems(conn)
    finally:
        conn.close()
    return rows, triggers


def _check_entry(row: tuple[Any, ...], prev_hash_expected: str, hash_to_seq: dict[Any, int],
                 problems: list[tuple[int, str]]) -> None:
    """Hash, canonical form and chain link of one entry."""
    seq, kind, payload_text, prev_hash, created_at, entry_hash = row[:6]
    problems.extend((seq, text) for text in
                    entry_content_problems(seq, kind, payload_text, prev_hash, created_at, entry_hash))
    if prev_hash != prev_hash_expected:
        other = hash_to_seq.get(prev_hash)
        if other is not None and other != seq:
            problems.append((seq, f"mata rantai terputus: prev_hash menunjuk entri #{other}, "
                                  "bukan entri tepat sebelumnya (urutan diubah)"))
        else:
            problems.append((seq, "mata rantai terputus: prev_hash tidak sama dengan hash entri sebelumnya"))


def _payload(text: Any) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError, RecursionError):
        return None  # already reported by entry_content_problems


def _document_eps(payload: Any) -> float | None:
    params = payload.get("params") if isinstance(payload, dict) else None
    eps = params.get("eps") if isinstance(params, dict) else None
    if not isinstance(eps, (int, float)) or isinstance(eps, bool):
        return None
    try:
        return float(eps)
    except OverflowError:  # an integer beyond the float range
        return None


def _check_trace(row: tuple[Any, ...], doc_eps: dict[str, float | None], counts: dict[str, int],
                 problems: list[tuple[int, str]]) -> None:
    """One ``trace`` entry: valid values, a recorded document with the same eps, the next number."""
    seq, created_at = row[0], row[4]
    payload = _payload(row[2])
    if payload is None:
        return
    found = trace_payload_problems(payload)
    problems.extend((seq, f"entri pelacakan: {text}") for text in found)
    if found:
        return
    doc = payload["doc_hash"]
    if doc not in doc_eps:
        problems.append((seq, "entri pelacakan untuk dokumen yang tidak tercatat sebelumnya di registri"))
        return
    if doc_eps[doc] is None or not math.isclose(payload["eps"], doc_eps[doc], rel_tol=1e-9):
        problems.append((seq, "eps entri pelacakan berbeda dari eps entri dokumennya"))
    expected = counts.get(doc, 0) + 1
    if payload["trace_no"] != expected:
        problems.append((seq, f"nomor pelacakan ke-{payload['trace_no']}, seharusnya ke-{expected} untuk dokumen "
                              f"{doc[:16]} (nomor ganda atau terlewat: catatan pelacakan tidak ditulis TAPAK)"))
    counts[doc] = counts.get(doc, 0) + 1
    if payload["created_at"] != created_at:
        problems.append((seq, "waktu di isi entri pelacakan berbeda dari waktu entri"))


def _check_anchors(rows: list[tuple[Any, ...]], anchors: Sequence[tuple[int, str]],
                   problems: list[tuple[int, str]]) -> None:
    """Every recorded (seq, entry_hash) anchor must still be in the registry, unchanged."""
    by_seq: dict[Any, Any] = {}
    for row in rows:
        by_seq.setdefault(row[0], row[5])
    for seq, anchor_hash in anchors:
        if seq not in by_seq:
            problems.append((seq, f"jangkar #{seq} tidak ditemukan: entri ini tidak ada lagi di registri "
                                  "(entri di ujung rantai dihapus?)"))
        elif str(by_seq[seq]).lower() != anchor_hash.strip().lower():
            problems.append((seq, "hash entri berbeda dari jangkar yang dicatat (entri ini atau entri "
                                  "sebelumnya diubah)"))


def verify_registry(
    db_path: str | Path,
    public_key_hex: str,
    merkle_dir: str | Path | None = None,
    require_signed: bool = True,
    anchors: Sequence[tuple[int, str]] | None = None,
) -> VerifyReport:
    """Verify hash chain, signatures, and optionally anchors and daily Merkle roots.

    ``require_signed`` (default) makes any unsigned entry a problem; with False it is a
    warning and the verdict names the unsigned entries. ``anchors`` are (seq, entry_hash)
    pairs recorded earlier outside the system. Raises SigningKeyError if
    ``public_key_hex`` is not 64 hex characters.
    """
    path = Path(db_path)
    report = VerifyReport(db_path=str(path), public_key=normalize_public_key(public_key_hex),
                          require_signed=require_signed)
    pub = report.public_key
    if not path.is_file():
        report.problems.append((0, "berkas registri tidak ditemukan"))
        return report
    try:
        rows, trigger_issues = _read_rows(path)
    except sqlite3.DatabaseError:
        report.problems.append((0, "berkas bukan registri TAPAK yang dapat dibaca (bukan SQLite atau "
                                   "tabel entri tidak ada)"))
        return report

    if trigger_issues:
        report.warnings.append(f"pemicu hanya-tambah tidak utuh ({'; '.join(trigger_issues)}): "
                               "berkas pernah disunting di luar TAPAK")
    problems = report.problems
    if not rows:
        problems.append((0, "registri kosong: tidak ada entri untuk diverifikasi (jika sebelumnya ada entri, "
                            "semuanya telah dihapus)"))

    hash_to_seq = {r[5]: r[0] for r in rows}
    expected_seq = 1
    prev_hash = ZERO_HASH
    prev_time = None
    pending_unsigned: list[int] = []
    unsigned_seqs: list[int] = []
    doc_eps: dict[str, float | None] = {}
    for row in rows:
        seq, kind, payload_text, _prev, created_at, entry_hash, signature, signer = row
        if kind == KIND_DOCUMENT:
            payload = _payload(payload_text)
            if isinstance(payload, dict) and isinstance(payload.get("doc_hash"), str):
                doc_eps.setdefault(payload["doc_hash"], _document_eps(payload))
            if isinstance(payload, dict) and set(payload) & LEXICAL_DOCUMENT_FIELDS:
                problems.extend((seq, f"entri dokumen: {text}") for text in lexical_document_problems(payload))
        elif kind == KIND_TRACE and isinstance(seq, int):
            _check_trace(row, doc_eps, report.traces, problems)
        report.entries += 1
        report.kinds[str(kind)] = report.kinds.get(str(kind), 0) + 1
        if not isinstance(seq, int):
            problems.append((0, f"nomor urut bukan bilangan bulat: {seq!r}"))
            continue
        if seq != expected_seq:
            if seq > expected_seq:
                problems.append((seq, f"nomor urut melompat: entri {_span(expected_seq, seq - 1)} hilang"))
            else:
                problems.append((seq, f"nomor urut tidak berurutan (diharapkan #{expected_seq})"))
        expected_seq = seq + 1

        _check_entry(row, prev_hash, hash_to_seq, problems)
        prev_hash = entry_hash

        try:
            t = parse_time(created_at)
            if prev_time is not None and t < prev_time:
                problems.append((seq, "waktu pencatatan mundur dibanding entri sebelumnya"))
            prev_time = t
        except (TypeError, ValueError):
            problems.append((seq, "waktu pencatatan tidak sah"))

        if signature is None and signer is None:
            pending_unsigned.append(seq)
            unsigned_seqs.append(seq)
            continue
        if pending_unsigned:
            problems.append((pending_unsigned[0], f"entri {_span(pending_unsigned[0], pending_unsigned[-1])} "
                                                  f"tidak bertanda tangan padahal entri #{seq} sesudahnya "
                                                  "bertanda tangan (tanda tangan dihapus?)"))
            pending_unsigned = []
        if signature is None or signer is None:
            problems.append((seq, "tanda tangan atau kunci penanda tangan tidak lengkap"))
            continue
        if str(signer).lower() != pub:
            problems.append((seq, f"ditandatangani kunci lain ({str(signer)[:16]}...), "
                                  "bukan kunci publik yang diperiksa"))
            continue
        try:
            message = bytes.fromhex(entry_hash)
        except (TypeError, ValueError):
            message = b""
        if len(message) != 32 or not verify_signature(pub, message, str(signature)):
            problems.append((seq, "tanda tangan tidak sah untuk hash entri ini"))

    if rows:
        report.head_seq, report.head_hash = rows[-1][0], rows[-1][5]
    if unsigned_seqs:
        report.unsigned = len(unsigned_seqs)
        report.unsigned_first, report.unsigned_last = unsigned_seqs[0], unsigned_seqs[-1]
        span = _span(unsigned_seqs[0], unsigned_seqs[-1])
        if require_signed:
            problems.append((unsigned_seqs[0], f"{len(unsigned_seqs)} entri ({span}) belum bertanda tangan, jadi "
                                               "tidak terlindungi dari pemalsuan (minta pemegang kunci menjalankan "
                                               "sign-pending, atau pakai --izinkan-belum-bertanda-tangan bila "
                                               "penandatanganan memang ditunda)"))
        else:
            report.warnings.append(f"{len(unsigned_seqs)} entri ({span}) belum bertanda tangan; entri itu hanya "
                                   "dilindungi rantai hash, yang dapat dihitung ulang oleh siapa pun")

    if anchors is not None:
        report.anchors_checked = len(anchors)
        _check_anchors(rows, anchors, problems)
    if merkle_dir is not None:
        try:
            report.merkle_files, merkle_problems = check_daily_roots(path, merkle_dir)
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            report.merkle_files, merkle_problems = 0, [(0, f"akar Merkle tidak dapat diperiksa: {describe_error(exc)}")]
        problems.extend(merkle_problems)
    return report


def main(argv: list[str] | None = None) -> int:
    """Console script ``tapak-verify-registry``: exit code 0 if the registry is intact, else 1."""
    ap = IndonesianArgumentParser(
        prog="tapak-verify-registry",
        description="Verifikasi registri TAPAK (rantai hash, tanda tangan, jangkar, akar Merkle) "
                    "hanya dengan kunci publik.")
    ap.add_argument("registry", help="berkas registri SQLite")
    ap.add_argument("--public-key", required=True, help="kunci publik heksadesimal atau berkas .pub")
    ap.add_argument("--merkle-dir", default=None, help="folder berkas akar Merkle harian untuk dicocokkan")
    ap.add_argument("--jangkar", action="append", default=None, metavar="NOMOR:HASH",
                    help="hash entri yang pernah dicatat di luar sistem; boleh diulang")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--izinkan-belum-bertanda-tangan", dest="allow_unsigned", action="store_true",
                      help="terima entri tanpa tanda tangan (penandatanganan ditunda); hasil tetap menyebutkannya")
    mode.add_argument("--require-signed", action="store_true",
                      help="anggap entri tanpa tanda tangan sebagai masalah (bawaan)")
    args = ap.parse_args(argv)
    try:
        public_key = load_public_key(args.public_key)
        anchors = [parse_anchor(a) for a in args.jangkar] if args.jangkar else None
        report = verify_registry(args.registry, public_key, args.merkle_dir,
                                 require_signed=not args.allow_unsigned, anchors=anchors)
    except (OSError, ValueError, sqlite3.Error) as exc:  # SigningKeyError and UnicodeError are ValueErrors
        print(f"Gagal: {describe_error(exc)}", file=sys.stderr)
        return 1
    for line in report.lines():
        print(line)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
