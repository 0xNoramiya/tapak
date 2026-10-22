"""Workflows shared by the CLI, the web app and the demo.

A *workspace* is one folder per issued document under ``data/dokumen/<doc>``:

    induk.pdf        the master (stays with the issuing unit, never in the registry)
    manifest.json    issuance record including the recipient roster (names stay here)
    varian.json      approved semantic variant sets, if any (document text, kept local)
    leksikal.json    reviewed word-choice points, if the document opted in (document text,
                     kept local; the registry holds only its digest)
    salinan/         the marked copies

The registry (``data/registry.db``) receives only hashes, ids and code commitments, and
logs every trace of a recorded document (hashes and numbers only) before decoding.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from tapak.config import Settings
from tapak.keys import load_code_secret, research_seed_of
from tapak.marker.issue import IssueManifest, IssueSettings, Recipient, SemanticSelection, issue
from tapak.marker.layout import sha256_hex
from tapak.marker.lexical import LexicalSelection
from tapak.tardos.spending import DEFAULT_STAGE_POLICY, TraceSpending

# Stage policy of every trace run through this module (CLI --doc and the web app): stage 1
# keeps 90 % of the trace's share, stages 2 to 4 split the rest (``tapak.tardos.spending``).
TRACE_STAGE_POLICY = DEFAULT_STAGE_POLICY


@dataclass
class Keys:
    """Key material available to this process."""

    code_secret: bytes
    signer: object | None          # tapak.registry.signing.Signer when the key is present
    public_key_hex: str | None


def ensure_keys(settings: Settings, create_signing_key: bool = True, create_secret: bool = True) -> Keys:
    """Load the code secret and, if present here, the registry signing key.

    A signing key is created only when ``create_signing_key`` is set AND no public key exists
    yet: an existing public key without its private half means the key is held elsewhere (a
    higher echelon), and creating a local one would silently replace the trusted signer. A
    loaded key must match the published public key.
    """
    from tapak.registry.signing import export_public_key, load_public_key, load_signer

    secret = load_code_secret(settings.code_secret_path, create=create_secret)
    signer = None
    sk, pk = settings.signing_key_path, settings.public_key_path
    held_elsewhere = pk.exists() and not sk.exists()
    if sk.exists() or (create_signing_key and not held_elsewhere):
        signer = load_signer(sk, create=True)
        if pk.exists():
            if load_public_key(pk) != signer.public_key_hex:
                raise ValueError(f"kunci tanda tangan {sk} tidak cocok dengan kunci publik {pk}")
        else:
            export_public_key(signer, pk)
    pub = load_public_key(pk) if pk.exists() else None
    return Keys(secret, signer, pub)


# --- external anchor log -----------------------------------------------------------------


def registry_keys(settings: Settings) -> tuple[object | None, str | None]:
    """(signer, public key hex) of the registry as present here, without the code secret.

    The signer is loaded only when its file exists and must match the published public key.
    """
    from tapak.registry.signing import load_public_key, load_signer

    sk, pk = settings.signing_key_path, settings.public_key_path
    public = load_public_key(pk) if pk.exists() else None
    signer = load_signer(sk) if sk.exists() else None
    if signer is not None and public is not None and signer.public_key_hex != public:
        raise ValueError(f"kunci tanda tangan {sk} tidak cocok dengan kunci publik {pk}")
    return signer, public or (signer.public_key_hex if signer is not None else None)


def anchor_log(settings: Settings, keys: Keys | None = None):
    """The anchor log configured for this process (``TAPAK_ANCHOR_LOG`` or ``--log-jangkar``),
    as a ``tapak.registry.anchor.AnchorLog``; None when no location is set.

    Lines are signed with the registry signing key when ``keys`` hold it, and signed lines are
    verified with the public key (read from its file when ``keys`` is None; the private key is
    then never loaded). A log inside the data or key folder is used, with a warning. Refuses
    (ValueError) the registry file itself as the location.
    """
    from tapak.registry.anchor import AnchorLog
    from tapak.registry.signing import SigningKeyError, load_public_key

    path = settings.anchor_log
    if path is None:
        return None
    if path.resolve() == settings.registry_path.resolve():
        raise ValueError("log jangkar tidak boleh berkas registri itu sendiri; pilih berkas di penyimpanan terpisah")
    signer, public = (keys.signer, keys.public_key_hex) if keys is not None else (None, None)
    if keys is None and settings.public_key_path.exists():
        try:
            public = load_public_key(settings.public_key_path)
        except (OSError, SigningKeyError):
            public = None
    return AnchorLog(path, signer=signer, public_key=public,  # type: ignore[arg-type]
                     protected=[settings.data_dir, settings.key_dir])


def anchor_status(settings: Settings, keys: Keys | None = None):
    """Read-only state of the anchor log against the registry (``AnchorStatus``); never raises.

    Without a configured log it still says whether the registry requires one (``required_by``).
    """
    import sqlite3

    from tapak.registry.anchor import AnchorStatus, read_registry_rows, unconfigured_status

    try:
        log = anchor_log(settings, keys)
    except ValueError as exc:
        return AnchorStatus(configured=True, path=str(settings.anchor_log), problems=[str(exc)], blocking=[str(exc)])
    if log is not None:
        return log.inspect_registry_file(settings.registry_path)
    try:
        rows = read_registry_rows(settings.registry_path)
    except sqlite3.Error:
        rows = []
    return unconfigured_status(rows)


def anchor_refusal(status) -> str | None:
    """Why traces and issuances must be refused because of the anchor log, or None.

    A configured log must match the registry; a registry that recorded the use of an anchor
    log refuses a process that has none configured, so the check is never skipped silently.
    """
    if status.configured:
        return None if status.ok else status.refusal()
    if status.required_by is not None:
        return (f"registri ini memakai log jangkar sejak entri #{status.required_by}, tetapi lokasi log jangkar tidak "
                "diatur di proses ini. Atur TAPAK_ANCHOR_LOG atau --log-jangkar ke lokasi log itu; tanpa log itu "
                "penghapusan entri dari ujung registri tidak terperiksa")
    return None


def _refuse_unanchored(reg) -> None:
    """Inside a write: refuse a registry that requires an anchor log this process lacks."""
    from tapak.registry.anchor import AnchorError, unconfigured_status

    refusal = anchor_refusal(unconfigured_status(reg.raw_rows()))
    if refusal:
        raise AnchorError(refusal)


# --- workspaces --------------------------------------------------------------------------


def workspace_dir(settings: Settings, doc_hash: str) -> Path:
    """Folder of one document."""
    return settings.workspaces / doc_hash[:16]


def list_workspaces(settings: Settings) -> list[IssueManifest]:
    """Manifests of all issued documents, newest first."""
    out = []
    if settings.workspaces.exists():
        for m in settings.workspaces.glob("*/manifest.json"):
            try:
                out.append(IssueManifest.from_json(m.read_text(encoding="utf-8")))
            except (ValueError, KeyError, TypeError):
                continue
    return sorted(out, key=lambda m: m.issued_at, reverse=True)


def _valid_doc_key(doc_key: str) -> str:
    """The 16-character workspace key of a document hash; refuses anything but lowercase hex.

    Keys arrive from URLs and forms, so this check is what keeps a request from naming a
    folder outside the data directory.
    """
    key = (doc_key or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{16,64}", key):
        raise FileNotFoundError("kode dokumen tidak valid")
    return key[:16]


def load_workspace(settings: Settings, doc_key: str) -> tuple[IssueManifest, bytes, Path]:
    """(manifest, master PDF bytes, folder) by doc hash or its 16-character prefix."""
    folder = settings.workspaces / _valid_doc_key(doc_key)
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"dokumen {doc_key[:16]} tidak ditemukan di {settings.workspaces}")
    manifest = IssueManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    master = folder / "induk.pdf"
    if not master.exists():
        master = folder / "induk.docx"
    return manifest, master.read_bytes(), folder


# --- issuance ----------------------------------------------------------------------------


@dataclass
class IssueOutcome:
    """Result of issuing a document."""

    manifest: IssueManifest
    folder: Path
    registry_entries: int
    signed: bool
    warnings: list[str] = field(default_factory=list)


def issue_document(
    settings: Settings,
    doc_path: Path,
    recipients: list[Recipient],
    issue_settings: IssueSettings,
    issuer: str,
    keys: Keys | None = None,
    record: bool = True,
    semantic: "SemanticSelection | None" = None,
    doc_name: str | None = None,
    lexical: LexicalSelection | None = None,
    latar: str | None = None,
    copy_ids: list[str] | None = None,
) -> IssueOutcome:
    """Issue copies of a PDF or DOCX into a new workspace and record them in the registry.

    ``doc_name`` is the original file name when ``doc_path`` is a temporary upload. A
    ``lexical`` selection (reviewed word-choice points) opts a PDF into the lexical channel;
    it is stored as ``leksikal.json`` next to the master, never in the registry. ``latar``
    picks the background profile by name ("layar", the default pattern, or "cetak", which
    survives printing but makes the page light gray); None keeps
    ``issue_settings.background``. With the print profile the outcome carries
    ``PRINT_BACKGROUND_WARNING``. ``copy_ids`` fixes the copy ids of a PDF issuance
    (research seed only, see ``tapak.keys``); None draws them at random.
    """
    from tapak.marker.background import PRINT_BACKGROUND, PRINT_BACKGROUND_WARNING, background_profile
    from tapak.registry.anchor import AnchorWriteError
    from tapak.registry.chain import Registry, registry_from_manifest

    if latar is not None:
        issue_settings = replace(issue_settings, background=background_profile(latar))

    # Never create a signing key implicitly: without it rows are recorded unsigned and the
    # key holder (a higher echelon) signs them later with `tapak registry sign`.
    keys = keys or ensure_keys(settings, create_signing_key=False)
    data = Path(doc_path).read_bytes()
    folder = workspace_dir(settings, sha256_hex(data))
    if (folder / "manifest.json").exists():
        raise FileExistsError(f"dokumen ini sudah diterbitkan (folder {folder}); gunakan dokumen lain")
    if record and keys.signer is not None and settings.registry_path.exists():
        from tapak.registry.chain import Registry as _Reg

        with _Reg.open(settings.registry_path) as reg:  # signing over unreviewed rows is refused
            if hasattr(reg, "pending") and reg.pending():
                raise ValueError("registri memiliki entri yang belum ditandatangani; pemegang kunci perlu "
                                 "menjalankan tapak registry sign lebih dulu")
    if record:  # before any copy is made; checked again under the registry's write lock
        refusal = anchor_refusal(anchor_status(settings, keys))
        if refusal:
            raise ValueError(f"penerbitan ditolak: {refusal}")
    doc_name = doc_name or Path(doc_path).name
    is_docx = Path(doc_name).suffix.lower() == ".docx"
    if lexical is not None and is_docx:
        raise ValueError("kanal pilihan kata hanya tersedia untuk dokumen induk PDF")
    if copy_ids is not None and is_docx:
        raise ValueError("id salinan tetap (benih riset) hanya tersedia untuk dokumen induk PDF")
    seed = research_seed_of(settings.code_secret_path)
    # A public secret must never mark a real document: a research key folder only issues
    # research copies (fixed copy ids), and never into a registry.
    if seed is not None and (copy_ids is None or record):
        raise ValueError(f"folder kunci {settings.code_secret_path.parent} berisi rahasia kode dari benih riset"
                         + (f" {seed}" if seed >= 0 else "") + ", yang publik; penerbitan biasa dan pencatatan "
                         "di registri ditolak. Pakai folder kunci lain")
    lock = _claim_workspace(folder)
    master_path = folder / ("induk.docx" if is_docx else "induk.pdf")
    master_path.write_bytes(data)
    committed = False
    try:
        if is_docx:
            manifest = _issue_docx(master_path, recipients, folder / "salinan", keys.code_secret,
                                   issue_settings, issuer, file_stem=Path(doc_name).stem)
        else:
            manifest = issue(master_path, recipients, folder / "salinan", keys.code_secret,
                             issue_settings, issuer=issuer, semantic=semantic, file_stem=Path(doc_name).stem,
                             lexical=lexical, copy_ids=copy_ids)
        manifest.doc_name = doc_name
        entries = 0
        anchor_warning = None
        if record:  # registry first: until it commits, any failure removes the whole workspace
            anchor = anchor_log(settings, keys)
            with Registry.open(settings.registry_path, anchor=anchor) as reg:
                if anchor is None:
                    _refuse_unanchored(reg)
                try:
                    entries = len(registry_from_manifest(manifest, reg, keys.signer,  # type: ignore[arg-type]
                                                         code_secret=keys.code_secret))
                except AnchorWriteError as exc:  # committed: only the anchor lines are missing
                    entries, anchor_warning = len(exc.entries), str(exc)
        committed = True
        (folder / ".tercatat").touch()  # recorded in the registry: never reclaimed as stale
        if semantic is not None and manifest.semantic_digest:
            _write_atomic(folder / "varian.json", json.dumps(semantic.to_dict(), indent=2, ensure_ascii=False))
        if lexical is not None and manifest.lexical_digest:
            _write_atomic(folder / "leksikal.json", lexical.to_json())
        if not is_docx:  # a copy next to the files for tools that read salinan/manifest.json
            _write_atomic(folder / "salinan" / "manifest.json", manifest.to_json())
        _write_atomic(folder / "manifest.json", manifest.to_json())  # last: it marks the issuance complete
    except BaseException as exc:  # also Ctrl-C: never leave a half-issued workspace claimed
        if not committed:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        raise RuntimeError(f"salinan sudah tercatat di registri tetapi catatan lokal gagal ditulis ({exc}); "
                           f"folder {folder} dipertahankan, jangan terbitkan ulang") from exc
    finally:
        lock.close()
    outcome = IssueOutcome(manifest, folder, entries, keys.signer is not None)
    if anchor_warning:
        outcome.warnings.append(f"{anchor_warning}; sampai saat itu pelacakan dan penerbitan ditolak")
    if manifest.background_settings == PRINT_BACKGROUND:
        outcome.warnings.append(PRINT_BACKGROUND_WARNING)
    if any(c.canary_token for c in manifest.copies):
        try:
            publish_canary_allowlist(settings)
        except OSError as exc:  # the issuance is committed; the allowlist can be rebuilt later
            outcome.warnings.append(f"daftar izin kanari tidak dapat ditulis ({exc.strerror or exc}); kueri untuk "
                                    "salinan ini akan diabaikan pendengar sampai daftar ditulis ulang dengan "
                                    "tapak kanari-izin")
    return outcome


def _write_atomic(path: Path, text: str) -> None:
    """Write a text file via a temporary name and rename, so it is never half written."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class WorkspaceBusy(FileExistsError):
    """The document is being issued now, or a previous issuance was recorded but not completed."""


def _claim_workspace(folder: Path):
    """Hold an OS lock for this document for the whole issuance, then create its folder.

    The lock file sits next to the folder (``<key>.lock``), so it exists before the folder and
    two issuances of the same document can never both pass. Under the lock, a folder without
    manifest.json is a stale claim (an issuance that was killed) and is removed, unless its
    copies were already recorded in the registry (marker ``.tercatat``).
    """
    import fcntl

    folder.parent.mkdir(parents=True, exist_ok=True)
    lock = open(folder.parent / (folder.name + ".lock"), "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise WorkspaceBusy(f"dokumen ini sedang diterbitkan oleh proses lain (folder {folder})") from None
    try:
        if (folder / "manifest.json").exists():
            raise FileExistsError(f"dokumen ini sudah diterbitkan (folder {folder})")
        if (folder / ".tercatat").exists():
            raise WorkspaceBusy(f"penerbitan dokumen ini sudah tercatat di registri tetapi catatan lokalnya tidak "
                                f"lengkap; periksa folder {folder} sebelum menerbitkan ulang")
        if folder.exists():
            shutil.rmtree(folder)  # stale claim from an interrupted issuance
        folder.mkdir()
    except BaseException:
        lock.close()
        raise
    return lock


def publish_canary_allowlist(settings: Settings) -> int:
    """Rewrite the listener's allowlist from the canary tokens of every issued document.

    Only SHA-256 digests are written. The list is rebuilt from the manifests (never read back
    from the file), written to a fresh random temporary name and renamed into place, under a
    lock, so concurrent issuances cannot lose digests and a planted link is replaced, never
    followed. Returns the number of digests.
    """
    import fcntl
    import os
    import tempfile

    from tapak.registry.chain import canary_token_digest

    folder = settings.canary_allow_dir
    folder.mkdir(parents=True, exist_ok=True)
    settings.workspaces.mkdir(parents=True, exist_ok=True)
    with open(settings.workspaces / ".kanari-izin.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Listed under the lock: a snapshot taken earlier could overwrite a newer one.
        digests = sorted({canary_token_digest(c.canary_token) for m in list_workspaces(settings)
                          for c in m.copies if c.canary_token})
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".token_digests.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="ascii") as fh:
                fh.write("".join(d + "\n" for d in digests))
            os.chmod(tmp, 0o644)  # the listener runs as another process and only reads it
            os.replace(tmp, settings.canary_allowlist)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return len(digests)


def _issue_docx(docx_path: Path, recipients: list[Recipient], out_dir: Path, secret: bytes,
                s: IssueSettings, issuer: str, file_stem: str | None = None) -> IssueManifest:
    """DOCX issuance (text-layer channel and canary only) recorded in an IssueManifest."""
    import time

    from tapak.marker.canary import add_docx_canary, canary_token, canary_url
    from tapak.marker.docx_marker import build_docx_plan, issue_docx, load_docx_master
    from tapak.marker.issue import IssuedCopy
    from tapak.marker.plan import plan_key
    from tapak.tardos.accuse import threshold
    from tapak.tardos.code import derive_bias
    from tapak.tardos.params import TardosParams

    t0 = time.perf_counter()
    params = TardosParams(c=s.c, eps=s.eps, n_max=s.n_max or len(recipients), constant=s.constant)  # type: ignore[arg-type]
    master = load_docx_master(docx_path.read_bytes())
    canary = "canary" in s.channels and bool(s.canary_domain)
    tokens: dict[str, str] = {}

    def per_copy(data: bytes, copy_id: str) -> bytes:
        if not canary:
            return data
        tokens[copy_id] = canary_token(secret, master.doc_hash, copy_id)
        return add_docx_canary(data, canary_url(tokens[copy_id], s.canary_domain))  # type: ignore[arg-type]

    rows = issue_docx(docx_path, recipients, out_dir, secret, params, post_process_copy=per_copy)
    if file_stem:  # name the copies after the original file, not the workspace's induk.docx
        renamed = []
        for seq, cid, path, digest in rows:
            new = Path(path).with_name(Path(path).name.replace(Path(docx_path).stem, file_stem, 1))
            Path(path).rename(new)
            renamed.append((seq, cid, new, digest))
        rows = renamed
    plan = build_docx_plan(master, params.length, plan_key(secret, master.doc_hash))
    used = [c for c in ("zw", "homoglyph") if plan.channel(c)] + (["canary"] if canary else [])
    copies = [IssuedCopy(seq=seq, copy_id=cid, recipient=recipients[seq - 1], file=Path(path).name,
                         file_sha256=sha256_hex(Path(path).read_bytes()), code_digest=digest,
                         channels_used=used, canary_token=tokens.get(cid))
              for seq, cid, path, digest in rows]
    return IssueManifest(
        doc_hash=master.doc_hash, doc_name=docx_path.name,
        issued_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), issuer=issuer,
        params=params.to_dict(), shift_mm={"word_mm": s.shift.word_mm, "row_mm": s.shift.row_mm},
        channels=used, excluded_rows=[], plan_summary=plan.summary(),
        threshold_full=threshold(derive_bias(secret, master.doc_hash, params), params.eps1),
        gate={"passed": True, "max_diff": 0, "mean_diff": 0.0, "dpi": 0, "note": "DOCX"},
        copies=copies, elapsed_s=time.perf_counter() - t0,
        canary_domain=s.canary_domain if canary else None,
    )


# --- tracing -----------------------------------------------------------------------------


@dataclass
class RegistryCheck:
    """Does the registry confirm the issuance record used for the trace?"""

    chain_ok: bool | None
    entries: int
    unsigned: int
    copies_confirmed: int
    copies_total: int
    problems: list[str] = field(default_factory=list)
    canary_log_ok: bool | None = None
    recorded: bool = True          # False: this document was issued without the registry
    copies_unsigned: int = 0       # registry rows of this document's copies without a signature
    mismatched: list[int] = field(default_factory=list)  # copy numbers whose record differs
    document_mismatch: list[str] = field(default_factory=list)  # code parameters that differ
    anchor: object | None = None   # tapak.registry.anchor.AnchorStatus (read-only, before the trace)


def check_registry(settings: Settings, manifest: IssueManifest, secret: bytes | None = None) -> RegistryCheck:
    """Verify the chain with the public key and confirm every copy's record: recipient id,
    number, code and file commitments and, given the code secret, the keyed commitment to the
    recipient's name, position and unit. ``anchor`` is the state of the external anchor log
    (``anchor_status``), compared with the registry before anything else is read."""
    from tapak.registry.chain import Registry, recipient_commitment
    from tapak.registry.verify import verify_registry

    anchor = anchor_status(settings)
    if not settings.registry_path.exists():
        return RegistryCheck(None, 0, 0, 0, len(manifest.copies), ["registri tidak ditemukan"], recorded=False,
                             anchor=anchor)
    problems: list[str] = []
    chain_ok: bool | None = None
    entries = unsigned = 0
    if settings.public_key_path.exists():
        # Deferred signing is a supported mode, so unsigned rows are reported, not fatal.
        rep = verify_registry(settings.registry_path, settings.public_key_path.read_text().strip(),
                              require_signed=False)
        chain_ok, entries, unsigned = rep.ok, rep.entries, rep.unsigned
        problems += [f"#{p[0]}: {p[1]}" if isinstance(p, tuple) else str(p) for p in rep.problems][:10]
    else:
        problems.append("kunci publik tidak tersedia; rantai tidak diverifikasi")
    with Registry.open(settings.registry_path) as reg:
        doc_rows = [e for e in reg.entries("document") if e.payload.get("doc_hash") == manifest.doc_hash]
        rows_by_copy: dict[str, list] = {}
        for e in reg.entries("copy"):
            if e.payload.get("doc_hash") == manifest.doc_hash:
                rows_by_copy.setdefault(e.payload["copy_id"], []).append(e)
    # The code parameters decide the threshold: they must be the recorded ones, not an edited
    # manifest's (a different eps, n_max or constant with the same code length keeps every code
    # commitment valid but lowers the bar for naming someone).
    document_mismatch: list[str] = []
    if len(doc_rows) > 1:
        document_mismatch.append("dokumen tercatat lebih dari sekali")
    elif doc_rows:
        recorded_doc = doc_rows[0].payload
        local = {"params": manifest.params, "channels": manifest.channels, "shift_mm": manifest.shift_mm,
                 "excluded_rows": manifest.excluded_rows, "threshold_full": manifest.threshold_full}
        from tapak.registry.chain import LEXICAL_DOCUMENT_FIELDS, SCAN_DOCUMENT_FIELD, SHIFT_SCHEME_DOCUMENT_FIELD

        # only where either side has it
        for key in sorted(LEXICAL_DOCUMENT_FIELDS) + [SCAN_DOCUMENT_FIELD, SHIFT_SCHEME_DOCUMENT_FIELD]:
            if getattr(manifest, key, None) is not None or key in recorded_doc:
                local[key] = getattr(manifest, key, None)
        for key, value in local.items():
            if json.loads(json.dumps(value)) != recorded_doc.get(key):
                document_mismatch.append(key)
    mismatched: list[int] = []
    for c in manifest.copies:
        rows = rows_by_copy.get(c.copy_id, [])
        rec = rows[0].payload if len(rows) == 1 else None  # a second row for a copy is never legitimate
        # Every field that ties a copy to a person must match the record, so an edited local
        # manifest (for example two recipients swapped, or a name changed) never names anyone.
        if rec is None or (rec.get("recipient_id"), rec.get("seq"), rec.get("code_digest"), rec.get("file_sha256")) != (
                c.recipient.recipient_id, c.seq, c.code_digest, c.file_sha256):
            mismatched.append(c.seq)
        elif "recipient_mac" not in rec or (secret is not None and rec["recipient_mac"] != recipient_commitment(
                secret, manifest.doc_hash, c.copy_id, c.recipient.recipient_id, c.recipient.nama,
                c.recipient.jabatan, c.recipient.satuan)):
            mismatched.append(c.seq)  # the name, position or unit is not the recorded one
    recorded = bool(doc_rows or rows_by_copy)
    confirmed = len(manifest.copies) - len(mismatched)
    copies_unsigned = sum(1 for rows in rows_by_copy.values() for e in rows if not e.signed)
    if recorded and mismatched:
        problems.append(f"{len(mismatched)} salinan tidak cocok dengan registri: #"
                        + ", #".join(str(n) for n in mismatched[:10]))
    if recorded and not doc_rows:
        document_mismatch.append("entri dokumen tidak ada")
    if document_mismatch:
        problems.append("parameter dokumen tidak cocok dengan registri: " + ", ".join(document_mismatch))
    if copies_unsigned:
        problems.append(f"{copies_unsigned} entri salinan dokumen ini belum bertanda tangan; rantai tanpa "
                        "tanda tangan tidak terlindungi dari pemalsuan oleh pemegang akses tulis")
    canary_ok = None
    try:
        from tapak.canary_dns.store import check_events_chain

        crep = check_events_chain(settings.canary_db)
        if crep.rows:
            canary_ok = crep.ok
            problems += [f"log kanari: {p}" for p in crep.problems][:5]
    except Exception as exc:  # noqa: BLE001 - a broken canary log must not stop the trace
        problems.append(f"log kanari tidak dapat diperiksa: {exc}")
    return RegistryCheck(chain_ok, entries, unsigned, confirmed, len(manifest.copies), problems, canary_ok,
                         recorded=recorded, copies_unsigned=copies_unsigned, mismatched=mismatched,
                         document_mismatch=document_mismatch, anchor=anchor)


def canary_alerts(settings: Settings, manifest: IssueManifest) -> list[dict[str, object]]:
    """Canary DNS hits for this document's copies (oldest first)."""
    if not settings.canary_db.exists():
        return []
    from tapak.canary_dns.store import events

    by_token = {c.canary_token: c for c in manifest.copies if c.canary_token}
    out = []
    try:
        evs = events(settings.canary_db)
    except Exception:  # noqa: BLE001 - no canary table yet
        return []
    for ev in evs:
        copy = by_token.get(ev.token)
        if copy is None:
            continue
        out.append({"seq": copy.seq, "recipient_id": copy.recipient.recipient_id, "nama": copy.recipient.nama,
                    "time": ev.received_at, "src_ip": ev.src_ip, "source_ip": ev.src_ip, "qtype": ev.qtype})
    return out


# Added to the result of every trace that the registry does not log.
UNLOGGED_TRACE_NOTE = ("pelacakan ini tidak dicatat di registri, jadi pelacakan berulang atas dokumen ini tidak "
                       "diperhitungkan: pelacakan ini memakai seluruh eps dan batas peluang tuduhan salah hanya berlaku "
                       "untuk pelacakan ini saja")
UNSIGNED_TRACE_NOTE = ("entri pelacakan ini dicatat di registri tanpa tanda tangan; pemegang kunci "
                       "menandatanganinya dengan tapak registry sign")


@dataclass
class TraceOutcome:
    """Everything a trace produced, ready for display or a report.

    ``trace_entry`` is the registry entry number that logged this trace (None when it was not
    logged) and ``trace_entry_hash`` its ``entry_hash``: together an anchor for
    ``tapak verify --jangkar``, printed in the berita acara, that exposes a later deletion of
    this entry (which would hand the next trace this trace's larger share again). The trace
    number and the eps it spent are in ``attribution.threshold`` (``trace_no``, ``eps_share``).
    ``anchor`` is the state of the external anchor log (``AnchorStatus``): checked before
    the trace entry was appended and, when configured, with that entry's line written.
    :meth:`anchor_line` is the one line the trace result shows about it.
    """

    attribution: object
    observations: list
    ctx: object
    evidence_name: str
    evidence_sha256: str
    registry: RegistryCheck
    canary: list[dict[str, object]]
    evidence_names: list[str] = field(default_factory=list)
    trace_entry: int | None = None
    trace_signed: bool = False
    trace_entry_hash: str | None = None
    anchor: object | None = None

    def anchor_line(self) -> str:
        """The anchor log sentence of the trace result, or "" when there is nothing to say.

        Shown for every logged trace (without a configured log it says that entries deleted
        from the end of the registry are only detected with an anchor) and whenever a log is
        configured.
        """
        anchor = self.anchor
        if anchor is None or not (self.trace_entry is not None or anchor.configured):  # type: ignore[attr-defined]
            return ""
        return str(anchor.describe())  # type: ignore[attr-defined]


def _log_trace(settings: Settings, keys: Keys, doc_hash: str, digests: list[str], eps: float,
               stage_policy: str | None = None, unanchored=None):
    """Append the ``trace`` entry of this trace before decoding; return it with the anchor state.

    ``stage_policy`` (the staged accusation's budget split) is written into the entry, so the
    eps of every stage is fixed in the registry before any evidence is read.

    Signed when the signing key is here, unless older entries still await review: signing now
    would be refused, since a signature must never cover rows nobody reviewed. A trace that
    cannot be logged is not performed, so a read-only or locked registry is no way around
    the count.

    With an anchor log, the log is compared with the registry under the write lock before the
    entry is appended (a mismatch refuses the trace), and the entry's line is written after
    the commit; if that line cannot be written the trace is not performed either (its number
    stays used). ``unanchored`` is the state returned when no anchor log is configured.
    """
    import sqlite3

    from tapak.decoder.trace import TraceError
    from tapak.registry.anchor import AnchorError, AnchorWriteError
    from tapak.registry.chain import Registry, RegistryError

    anchor = anchor_log(settings, keys)
    try:
        with Registry.open(settings.registry_path, anchor=anchor) as reg:
            if anchor is None:
                _refuse_unanchored(reg)
            with reg.transaction():
                signer = keys.signer if keys.signer is not None and not reg.pending() else None
                entry = reg.record_trace(doc_hash=doc_hash, evidence_sha256=digests, eps=eps,
                                         signer=signer, stage_policy=stage_policy)  # type: ignore[arg-type]
        return entry, (anchor.status if anchor is not None else unanchored)
    except AnchorWriteError as exc:
        raise TraceError(f"{exc}. Pelacakan dibatalkan sebelum bukti dibaca dan tidak ada nama yang disebut; nomor "
                         "pelacakan ini tetap terpakai") from exc
    except AnchorError as exc:
        raise TraceError(f"pelacakan ditolak sebelum bukti dibaca: {exc}. Tidak ada nama yang disebut") from exc
    except (sqlite3.Error, RegistryError, OSError, ValueError) as exc:
        raise TraceError(f"pelacakan tidak dapat dicatat di registri ({exc}); pelacakan dibatalkan dan "
                         "tidak ada nama yang disebut") from exc


def trace_evidence(settings: Settings, doc_key: str, evidence_name: str, evidence: bytes,
                   keys: Keys | None = None, more: list[tuple[str, bytes]] | None = None) -> TraceOutcome:
    """Decode evidence against an issued document; ``more`` adds further files of the same leak
    (for example photos of the other pages), fused into one attribution.

    For a document recorded in the registry, the trace is logged before decoding and spends
    only its share of eps: trace number k gets eps * 6 / (pi^2 k^2), so all traces of the
    document together stay within eps. Without a registry record the trace spends all of eps
    and the result says that repeated traces are not accounted for.

    Every trace runs the staged accusation with ``TRACE_STAGE_POLICY`` (``tapak.tardos.staged``):
    the policy and the eps of every stage go into the trace's registry entry with its number,
    before decoding, and the trace's share is split over the stages by that fixed policy.
    """
    from tapak.decoder.trace import check_evidence_types, load_context, trace_files

    # Tracing never creates keys: a missing code secret is an error, not a reason to make one.
    keys = keys or ensure_keys(settings, create_signing_key=False, create_secret=False)
    manifest, master, folder = load_workspace(settings, doc_key)
    from tapak.decoder.trace import TraceError

    # The registry is checked before decoding: the code parameters, the copies and the identity
    # of every recipient must be the recorded ones, or nobody is named.
    reg = check_registry(settings, manifest, keys.code_secret)
    refuse = "; tidak ada nama yang disebut sampai perbedaan ini diperiksa"
    # The anchor log first: it is the only check that sees entries deleted from the end.
    anchor_refused = anchor_refusal(reg.anchor) if reg.anchor is not None else None
    if anchor_refused:
        raise TraceError(f"pelacakan ditolak: {anchor_refused}. Tidak ada nama yang disebut")
    if settings.public_key_path.exists() and not reg.recorded:
        raise TraceError("dokumen ini tidak ditemukan di registri (berkas registri hilang, terpotong, atau "
                         "dokumen diterbitkan tanpa registri), sehingga identitas penerima tidak dapat "
                         "dikonfirmasi" + refuse)
    if reg.recorded and reg.chain_ok is False:
        raise TraceError("verifikasi rantai registri gagal (" + "; ".join(reg.problems[:3]) + "); identitas "
                         "penerima tidak dapat dikonfirmasi sehingga tidak ada nama yang disebut. Periksa registri "
                         "dengan tapak verify")
    if reg.recorded and reg.document_mismatch:
        raise TraceError("parameter kode di catatan penerbitan lokal tidak cocok dengan registri ("
                         + ", ".join(reg.document_mismatch) + ")" + refuse)
    if reg.recorded and reg.mismatched:
        raise TraceError("catatan penerbitan lokal tidak cocok dengan registri bertanda tangan untuk salinan #"
                         + ", #".join(str(n) for n in reg.mismatched[:10]) + refuse)
    items = [(evidence_name, evidence)] + list(more or [])
    is_docx = (folder / "induk.docx").exists()
    ctx = None
    if not is_docx:  # checks that need no evidence come first, so they never use up a trace number
        check_evidence_types([n for n, _ in items])
        ctx = load_context(master, manifest, keys.code_secret, folder=folder)
    digests = [sha256_hex(d) for _, d in items]
    eps = manifest.tardos_params.eps
    entry = None
    anchor = reg.anchor
    if reg.recorded:  # logged first: the trace number and stage budgets, so the thresholds, precede decoding
        entry, anchor = _log_trace(settings, keys, manifest.doc_hash, digests, eps, TRACE_STAGE_POLICY,
                                   unanchored=reg.anchor)
        spending = TraceSpending.logged(eps, entry.payload["trace_no"], entry.payload.get("stage_policy"))
    else:
        spending = TraceSpending.unlogged(eps, TRACE_STAGE_POLICY)
    if ctx is None:
        attribution, obs, ctx = _trace_docx(master, manifest, keys.code_secret, items, spending)
    else:
        attribution, obs = trace_files(items, ctx, spending)
    if not reg.recorded:
        attribution.notes.append("dokumen ini diterbitkan tanpa registri; identitas penerima hanya berasal dari "
                                 "catatan lokal dan tidak dapat dikonfirmasi pihak ketiga")
        attribution.notes.append(UNLOGGED_TRACE_NOTE)
    elif not entry.signed:
        attribution.notes.append(UNSIGNED_TRACE_NOTE)
    names = ", ".join(n for n, _ in items)
    return TraceOutcome(attribution, obs, ctx, names, ", ".join(digests), reg, canary_alerts(settings, manifest),
                        [n for n, _ in items], trace_entry=entry.seq if entry else None,
                        trace_signed=bool(entry and entry.signed),
                        trace_entry_hash=entry.entry_hash if entry else None, anchor=anchor)


def _trace_docx(master_bytes: bytes, manifest: IssueManifest, secret: bytes,
                items: list[tuple[str, bytes]],
                spending: TraceSpending | None = None) -> tuple[object, list, object]:
    """Trace text, DOCX or PDF evidence against a DOCX master (text-layer channel); several
    files of the same leak are fused. ``spending`` is this trace's part of eps
    (``TraceSpending``; None: not logged, all of eps)."""
    from types import SimpleNamespace

    import numpy as np

    from tapak.decoder.accuse import CopyRef, attribute
    from tapak.decoder.ch_docx import decode_docx, extract_docx_text
    from tapak.decoder.ch_zerowidth import extract_pdf_text
    from tapak.decoder.fuse import fuse, fuse_by_physical_channel
    from tapak.decoder.trace import TraceError
    from tapak.marker.docx_marker import build_docx_plan, load_docx_master
    from tapak.marker.plan import plan_key
    from tapak.tardos.code import code_digest, derive_bias, derive_codeword

    try:
        master = load_docx_master(master_bytes)
    except Exception as exc:  # noqa: BLE001 - zip/xml errors from a damaged file
        raise TraceError("dokumen induk DOCX tidak dapat dibaca (rusak atau bukan DOCX)") from exc
    if master.doc_hash != manifest.doc_hash:
        raise TraceError("dokumen induk tidak cocok dengan catatan penerbitan (hash berbeda)")
    params = manifest.tardos_params
    plan = build_docx_plan(master, params.length, plan_key(secret, master.doc_hash))
    p = derive_bias(secret, master.doc_hash, params)
    rows, refs = [], []
    for c in manifest.copies:
        x = derive_codeword(secret, master.doc_hash, c.copy_id, p)
        if code_digest(master.doc_hash, c.copy_id, x) != c.code_digest:
            raise TraceError(f"komitmen kode salinan #{c.seq} tidak cocok")
        rows.append(x)
        refs.append(CopyRef(c.seq, c.copy_id, c.recipient.recipient_id, c.recipient.nama,
                            c.recipient.jabatan, c.recipient.satuan))
    from tapak.decoder.trace import decode_text_evidence

    obs, notes = [], []
    for name, data in items:
        suffix = Path(name).suffix.lower()
        try:
            if suffix == ".docx":
                text = extract_docx_text(data)
            elif suffix == ".pdf":
                text = extract_pdf_text(data)
            else:
                text = decode_text_evidence(data)
        except Exception as exc:  # noqa: BLE001 - damaged evidence file
            raise TraceError(f"{name}: berkas bukti tidak dapat dibaca") from exc
        if "\ufffd" in text:
            notes.append(f"{name}: sebagian karakter tidak dapat diterjemahkan (pengodean teks tidak dikenal)")
        obs += decode_docx(text, master, plan)
    codewords = np.vstack(rows)
    result = attribute(fuse(obs, params.length), fuse_by_physical_channel(obs, params.length), p,
                       codewords, refs, params, spending)
    if len(items) > 1:
        notes.insert(0, f"{len(items)} berkas bukti digabung dalam satu atribusi")
    result.notes = notes + result.notes
    ctx = SimpleNamespace(master=SimpleNamespace(doc_hash=master.doc_hash, pdf_bytes=b""), manifest=manifest,
                          params=params, plan=plan, p=p, codewords=codewords, refs=refs)
    return result, obs, ctx


def write_report(outcome: TraceOutcome, out_path: Path | None = None, case_number: str = "",
                 examiner_name: str = "", examiner_rank: str = "") -> bytes:
    """Berita acara PDF for a trace outcome."""
    from tapak.decoder.report import build_report_info, evidence_types_for, render_report

    reg = outcome.registry
    names = outcome.evidence_names or [outcome.evidence_name]
    info = build_report_info(
        outcome.ctx, outcome.evidence_name, b"", outcome.observations, evidence_type=evidence_types_for(names),
        case_number=case_number or f"TAPAK-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
        examiner_name=examiner_name or "(nama pemeriksa)", examiner_rank=examiner_rank or "(pangkat/NRP)",
        registry_ok=reg.chain_ok, registry_entries=reg.entries, canary_events=outcome.canary,
    )
    info.registry_unsigned = reg.copies_unsigned
    info.trace_entry, info.trace_entry_hash = outcome.trace_entry, outcome.trace_entry_hash or ""
    info.anchor_text = outcome.anchor_line() if outcome.trace_entry is not None else ""
    info.evidence_sha256 = outcome.evidence_sha256
    info.evidence_names = names if len(names) > 1 else []
    return render_report(outcome.attribution, info, out_path)


def save_json(path: Path, obj: object) -> None:
    """Write pretty JSON (UTF-8)."""
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
