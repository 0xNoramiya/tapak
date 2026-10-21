"""Workflows shared by the CLI, the web app and the demo.

A *workspace* is one folder per issued document under ``data/dokumen/<doc>``:

    induk.pdf        the master (stays with the issuing unit, never in the registry)
    manifest.json    issuance record including the recipient roster (names stay here)
    varian.json      approved semantic variant sets, if any (document text, kept local)
    salinan/         the marked copies

The registry (``data/registry.db``) receives only hashes, ids and code commitments.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from tapak.config import Settings
from tapak.keys import load_code_secret
from tapak.marker.issue import IssueManifest, IssueSettings, Recipient, SemanticSelection, issue
from tapak.marker.layout import sha256_hex


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
) -> IssueOutcome:
    """Issue copies of a PDF or DOCX into a new workspace and record them in the registry.

    ``doc_name`` is the original file name when ``doc_path`` is a temporary upload.
    """
    from tapak.registry.chain import Registry, registry_from_manifest

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
    lock = _claim_workspace(folder)
    doc_name = doc_name or Path(doc_path).name
    is_docx = Path(doc_name).suffix.lower() == ".docx"
    master_path = folder / ("induk.docx" if is_docx else "induk.pdf")
    master_path.write_bytes(data)
    committed = False
    try:
        if is_docx:
            manifest = _issue_docx(master_path, recipients, folder / "salinan", keys.code_secret,
                                   issue_settings, issuer, file_stem=Path(doc_name).stem)
        else:
            manifest = issue(master_path, recipients, folder / "salinan", keys.code_secret,
                             issue_settings, issuer=issuer, semantic=semantic, file_stem=Path(doc_name).stem)
        manifest.doc_name = doc_name
        entries = 0
        if record:  # registry first: until it commits, any failure removes the whole workspace
            with Registry.open(settings.registry_path) as reg:
                entries = len(registry_from_manifest(manifest, reg, keys.signer,  # type: ignore[arg-type]
                                                     code_secret=keys.code_secret))
        committed = True
        (folder / ".tercatat").touch()  # recorded in the registry: never reclaimed as stale
        if semantic is not None and manifest.semantic_digest:
            _write_atomic(folder / "varian.json", json.dumps(semantic.to_dict(), indent=2, ensure_ascii=False))
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


def _claim_workspace(folder: Path):
    """Create the document folder and hold an OS lock on it for the whole issuance.

    A folder without manifest.json whose lock is free is a stale claim (an issuance that was
    killed): it is removed and claimed again, unless its copies were already recorded in the
    registry (marker ``.tercatat``). A folder whose lock is held is being issued now.
    """
    import fcntl

    folder.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            folder.mkdir()
        except FileExistsError:
            if (folder / "manifest.json").exists():
                raise FileExistsError(f"dokumen ini sudah diterbitkan (folder {folder})") from None
            if (folder / ".tercatat").exists():
                raise FileExistsError(f"penerbitan dokumen ini sudah tercatat di registri tetapi catatan lokalnya tidak "
                                      f"lengkap; periksa folder {folder} sebelum menerbitkan ulang") from None
            probe = open(folder / ".terbit.lock", "a+")
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                probe.close()
                raise FileExistsError(f"dokumen ini sedang diterbitkan (folder {folder})") from None
            probe.close()
            shutil.rmtree(folder, ignore_errors=True)  # stale claim from an interrupted issuance
            continue
        lock = open(folder / ".terbit.lock", "a+")
        fcntl.flock(lock, fcntl.LOCK_EX)
        return lock
    raise FileExistsError(f"folder dokumen {folder} tidak dapat diklaim")


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

    digests = sorted({canary_token_digest(c.canary_token) for m in list_workspaces(settings)
                      for c in m.copies if c.canary_token})
    folder = settings.canary_allow_dir
    folder.mkdir(parents=True, exist_ok=True)
    settings.workspaces.mkdir(parents=True, exist_ok=True)
    with open(settings.workspaces / ".kanari-izin.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
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


def check_registry(settings: Settings, manifest: IssueManifest, secret: bytes | None = None) -> RegistryCheck:
    """Verify the chain with the public key and confirm every copy's record: recipient id,
    number, code and file commitments and, given the code secret, the keyed commitment to the
    recipient's name, position and unit."""
    from tapak.registry.chain import Registry, recipient_commitment
    from tapak.registry.verify import verify_registry

    if not settings.registry_path.exists():
        return RegistryCheck(None, 0, 0, 0, len(manifest.copies), ["registri tidak ditemukan"])
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
        entries_by_copy = {e.payload["copy_id"]: e for e in reg.entries("copy")
                           if e.payload.get("doc_hash") == manifest.doc_hash}
    recorded = {k: e.payload for k, e in entries_by_copy.items()}
    mismatched: list[int] = []
    uncommitted = 0
    for c in manifest.copies:
        rec = recorded.get(c.copy_id)
        # Every field that ties a copy to a person must match the signed record, so an edited
        # local manifest (for example two recipients swapped) can never name the wrong person.
        if rec is None or (rec.get("recipient_id"), rec.get("seq"), rec.get("code_digest"), rec.get("file_sha256")) != (
                c.recipient.recipient_id, c.seq, c.code_digest, c.file_sha256):
            mismatched.append(c.seq)
        elif "recipient_mac" not in rec:
            uncommitted += 1
        elif secret is not None and rec["recipient_mac"] != recipient_commitment(
                secret, manifest.doc_hash, c.copy_id, c.recipient.recipient_id, c.recipient.nama,
                c.recipient.jabatan, c.recipient.satuan):
            mismatched.append(c.seq)  # the name, position or unit was edited after issuance
    confirmed = len(manifest.copies) - len(mismatched)
    copies_unsigned = sum(1 for e in entries_by_copy.values() if not e.signed)
    if recorded and mismatched:
        problems.append(f"{len(mismatched)} salinan tidak cocok dengan registri: #"
                        + ", #".join(str(n) for n in mismatched[:10]))
    if copies_unsigned:
        problems.append(f"{copies_unsigned} entri salinan dokumen ini belum bertanda tangan; rantai tanpa "
                        "tanda tangan tidak terlindungi dari pemalsuan oleh pemegang akses tulis")
    if uncommitted:
        problems.append(f"{uncommitted} entri salinan tidak memuat komitmen nama penerima (diterbitkan versi lama); "
                        "nama, jabatan dan satuan hanya berasal dari catatan lokal")
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
                         recorded=bool(recorded), copies_unsigned=copies_unsigned, mismatched=mismatched)


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


@dataclass
class TraceOutcome:
    """Everything a trace produced, ready for display or a report."""

    attribution: object
    observations: list
    ctx: object
    evidence_name: str
    evidence_sha256: str
    registry: RegistryCheck
    canary: list[dict[str, object]]
    evidence_names: list[str] = field(default_factory=list)


def trace_evidence(settings: Settings, doc_key: str, evidence_name: str, evidence: bytes,
                   keys: Keys | None = None, more: list[tuple[str, bytes]] | None = None) -> TraceOutcome:
    """Decode evidence against an issued document; ``more`` adds further files of the same leak
    (for example photos of the other pages), fused into one attribution."""
    from tapak.decoder.trace import load_context, trace_files

    # Tracing never creates keys: a missing code secret is an error, not a reason to make one.
    keys = keys or ensure_keys(settings, create_signing_key=False, create_secret=False)
    manifest, master, folder = load_workspace(settings, doc_key)
    items = [(evidence_name, evidence)] + list(more or [])
    if (folder / "induk.docx").exists():
        attribution, obs, ctx = _trace_docx(master, manifest, keys.code_secret, items)
    else:
        ctx = load_context(master, manifest, keys.code_secret, folder=folder)
        attribution, obs = trace_files(items, ctx)
    reg = check_registry(settings, manifest, keys.code_secret)
    if reg.recorded and reg.chain_ok is False:
        from tapak.decoder.trace import TraceError

        raise TraceError("verifikasi rantai registri gagal (" + "; ".join(reg.problems[:3]) + "); identitas "
                         "penerima tidak dapat dikonfirmasi sehingga tidak ada nama yang disebut. Periksa registri "
                         "dengan tapak verify")
    if reg.recorded and reg.mismatched:
        from tapak.decoder.trace import TraceError

        raise TraceError("catatan penerbitan lokal tidak cocok dengan registri bertanda tangan untuk salinan #"
                         + ", #".join(str(n) for n in reg.mismatched[:10])
                         + "; tidak ada nama yang disebut sampai perbedaan ini diperiksa")
    if not reg.recorded:
        attribution.notes.append("dokumen ini diterbitkan tanpa registri; identitas penerima hanya berasal dari "
                                 "catatan lokal dan tidak dapat dikonfirmasi pihak ketiga")
    if reg.copies_unsigned:
        attribution.notes.append(f"{reg.copies_unsigned} entri registri salinan belum bertanda tangan")
    names = ", ".join(n for n, _ in items)
    digest = sha256_hex(evidence) if len(items) == 1 else ", ".join(sha256_hex(d) for _, d in items)
    return TraceOutcome(attribution, obs, ctx, names, digest, reg, canary_alerts(settings, manifest),
                        [n for n, _ in items])


def _trace_docx(master_bytes: bytes, manifest: IssueManifest, secret: bytes,
                items: list[tuple[str, bytes]]) -> tuple[object, list, object]:
    """Trace text, DOCX or PDF evidence against a DOCX master (text-layer channel); several
    files of the same leak are fused."""
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
                       codewords, refs, params)
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
    info.evidence_sha256 = outcome.evidence_sha256
    info.evidence_names = names if len(names) > 1 else []
    return render_report(outcome.attribution, info, out_path)


def save_json(path: Path, obj: object) -> None:
    """Write pretty JSON (UTF-8)."""
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
