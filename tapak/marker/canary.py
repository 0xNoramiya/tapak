"""Channel 5: canary token (one DNS name per issued copy).

Every issued copy gets one unique host name ``<token>.c.<domain>`` under a canary domain
that TAPAK's authoritative DNS listener serves (see ``tapak.canary_dns``). The copy
references that host in a way some viewers act on when they open the file. When a copy is
opened on a machine whose resolver is outside the unit's network, that resolver asks the
listener for the name, and the listener logs the token, the query type, the source address
of the resolver and the time. The token maps back to one copy through the issuance record.

What triggers it (honest list):

* PDF: a document-level ``/OpenAction`` URI action. Adobe Acrobat and Adobe Reader run it
  when the file opens; they ask the user whether to allow the connection and look the host
  name up around that prompt (the technique behind the canarytokens.org Acrobat token).
  Whether the lookup happens before or only after the user answers depends on the Reader
  version and its Enhanced Security settings. Browser viewers (Chrome/Edge PDFium,
  Firefox pdf.js), MuPDF, macOS Preview and most Linux viewers do not run open actions
  and therefore never fetch anything: no event fires there.
  The cost: the open action is not silent. Every Adobe Reader user, including every
  legitimate recipient inside the network, sees a warning such as "this document is
  trying to connect to http://<token>.c.<domain>/" on every open. That advertises the
  canary and its token and invites stripping it. If the user clicks Allow, the browser
  opens the URL; inside the network the internal resolver answers it, outside it
  resolves to the listener's ``answer_ip`` (by default 127.0.0.1, the opener's own
  machine). The issuing operator should therefore enable the canary per issuance
  (``IssueSettings.canary_domain``) only where that trade-off is acceptable.
* DOCX: an external image relationship (``TargetMode="External"``) used by a one-pixel
  inline picture. Microsoft Word resolves and fetches linked pictures when it opens the
  document. Files that arrive by mail or download open in Protected View, which blocks
  external content until the user clicks "Enable Editing"; the fetch happens then. Word
  does not fetch external fonts, so fonts are not used. LibreOffice and web previews
  (Office Online, Google Docs) are not relied upon.

The canary is supporting evidence, not part of the Tardos accusation: anyone who inspects
the file can strip the reference, and members of a coalition can see (and swap) each
other's tokens. Its value is a time and network-location signal for a copy that is being
opened where it should not be.

Inside the unit's network nothing fires because the internal recursive resolver answers
the canary zone itself and never asks the outside world. Configure it with a local
authoritative zone (or wildcard) for ``c.<domain>``, for example:

* Unbound: ``local-zone: "c.<domain>." redirect`` plus
  ``local-data: "c.<domain>. 0 IN A 10.0.0.1"`` (``redirect`` answers every name below
  the zone with that record, i.e. a wildcard);
* BIND: an internal ``zone "<domain>"`` of type master containing ``*.c IN A 10.0.0.1``,
  or a response policy zone (RPZ) entry ``*.c.<domain> CNAME .``;
* dnsmasq: ``address=/c.<domain>/10.0.0.1``.

Machines inside the network must not bypass the internal resolver (for example with a
browser's built-in DNS over HTTPS), or they would trigger false alarms.

Data minimization: the token is an opaque HMAC value; neither the file nor the DNS query
contains document text, recipient names or any secret.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import io
import re
import zipfile
import zlib
from collections.abc import Callable
from urllib.parse import urlsplit

import pikepdf
import pymupdf
from lxml import etree

CANARY_LABEL = "c"
TOKEN_LENGTH = 16
TOKEN_RE = re.compile(r"[a-z2-7]{16}")
_LABEL_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_TOKEN_LABEL = b"TAPAK-canary-v1|"

# One pixel at 96 dpi in English Metric Units (Word's length unit).
PIXEL_EMU = 9525
_REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Limits for reading untrusted (possibly leaked or hostile) files.
MAX_ACTIONS = 256  # PDF actions visited per file, following /Next chains
MAX_RELS_PARTS = 1000  # .rels parts read per DOCX package
MAX_RELS_BYTES = 1_000_000  # bytes per .rels part; larger parts are skipped


def canary_token(secret: bytes, doc_hash: str, copy_id: str) -> str:
    """Opaque per-copy token: HMAC-SHA256, lowercase base32, first 16 characters (80 bits).

    The alphabet is ``a-z`` and ``2-7``, so the token is a valid DNS label. ``doc_hash`` is a
    fixed-length hex digest, so the ``|``-separated message is unambiguous. The token
    reveals nothing about the secret, the codeword or the recipient.
    """
    msg = _TOKEN_LABEL + doc_hash.encode() + b"|" + copy_id.encode()
    mac = hmac.new(secret, msg, hashlib.sha256).digest()
    return base64.b32encode(mac).decode("ascii").lower()[:TOKEN_LENGTH]


def normalize_domain(domain: str) -> str:
    """Lowercase canary domain without trailing dot; ValueError if it is not a host name."""
    d = domain.strip().rstrip(".").lower()
    labels = d.split(".")
    if not d or len(d) > 200 or not all(_LABEL_RE.fullmatch(lab) for lab in labels):
        raise ValueError(f"domain kanari tidak valid: {domain!r}")
    return d


def canary_hostname(token: str, domain: str) -> str:
    """The copy's canary host name ``<token>.c.<domain>``."""
    if not TOKEN_RE.fullmatch(token):
        raise ValueError(f"token kanari tidak valid: {token!r}")
    return f"{token}.{CANARY_LABEL}.{normalize_domain(domain)}"


def canary_url(token: str, domain: str) -> str:
    """Plain http URL of the canary host (contains only the opaque token)."""
    return f"http://{canary_hostname(token, domain)}/"


def token_from_qname(qname: str, domain: str) -> str | None:
    """Token carried by a DNS name, or None if the name is not ``<token>.c.<domain>``.

    Comparison is case-insensitive, so names with DNS 0x20 case randomization (resolvers
    flip the case of letters to harden against spoofing) are recognized.
    """
    name = qname.strip().rstrip(".").lower()
    suffix = f".{CANARY_LABEL}.{normalize_domain(domain)}"
    if not name.endswith(suffix):
        return None
    label = name[: -len(suffix)]
    return label if TOKEN_RE.fullmatch(label) else None


# --- PDF ---------------------------------------------------------------------------------


def add_pdf_canary(doc: pymupdf.Document, url: str) -> None:
    """Make the document's open action a URI action pointing at ``url``.

    Usable as a doc hook of ``CopyMarks.doc_hooks`` (bind ``url`` with
    :func:`pdf_canary_hook`). An existing open action (a destination or an action) is kept
    and chained with ``/Next``, so the initial view does not change. Page content is not
    touched, so rendering and text extraction stay exactly the same.
    """
    if not url.isascii():
        raise ValueError("URL kanari harus ASCII")
    cat = doc.pdf_catalog()
    kind, value = doc.xref_get_key(cat, "OpenAction")
    nxt = ""
    if kind != "null":
        is_action = kind == "dict" or (
            kind == "xref" and doc.xref_object(int(value.split()[0]), compressed=True).startswith("<<")
        )
        nxt = f"/Next {value}" if is_action else f"/Next <</S/GoTo/D {value}>>"
    xref = doc.get_new_xref()
    doc.update_object(xref, f"<</Type/Action/S/URI/URI{pymupdf.get_pdf_str(url)}{nxt}>>")
    doc.xref_set_key(cat, "OpenAction", f"{xref} 0 R")


def pdf_canary_hook(url: str) -> Callable[[pymupdf.Document], None]:
    """A picklable doc hook for :class:`tapak.marker.render.CopyMarks` that adds the canary."""
    return functools.partial(add_pdf_canary, url=url)


def add_pdf_canary_to_bytes(pdf_bytes: bytes, url: str) -> bytes:
    """Convenience: add the canary to an existing PDF file and return the new bytes."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        add_pdf_canary(doc, url)
        return doc.tobytes(garbage=3, deflate=True)


def _host(url: object) -> str | None:
    try:
        host = urlsplit(str(url)).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _uri_actions(roots: list[object], limit: int = MAX_ACTIONS) -> list[str]:
    """URIs of the given PDF actions and of every action chained after them with /Next.

    Walks with an explicit stack (no recursion) and visits at most ``limit`` objects, so a
    crafted file with a very long or cyclic /Next chain cannot exhaust the stack or the CPU.
    """
    out: list[str] = []
    seen: set[tuple[int, int]] = set()
    stack = list(reversed(roots))
    visited = 0
    while stack and visited < limit:
        action = stack.pop()
        visited += 1
        if isinstance(action, pikepdf.Array):
            stack.extend(reversed(list(action)))
            continue
        if not isinstance(action, pikepdf.Dictionary):
            continue
        if action.is_indirect:
            if action.objgen in seen:
                continue
            seen.add(action.objgen)
        if action.get("/S") == pikepdf.Name.URI and "/URI" in action:
            out.append(str(action.URI))
        if "/Next" in action:
            stack.append(action.Next)
    return out


def _pdf_hosts(data: bytes) -> list[str]:
    """Hosts of URI actions a viewer runs automatically: open action and /AA triggers."""
    try:
        with pikepdf.open(io.BytesIO(data)) as pdf:
            root = pdf.Root
            roots: list[object] = [root.OpenAction] if "/OpenAction" in root else []
            for aa in [root.get("/AA")] + [page.obj.get("/AA") for page in pdf.pages]:
                if isinstance(aa, pikepdf.Dictionary):
                    roots += [aa[key] for key in aa.keys()]
            uris = _uri_actions(roots)
    except (pikepdf.PdfError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError("berkas PDF tidak dapat dibaca") from exc
    return [h for h in (_host(u) for u in uris) if h]


# --- DOCX --------------------------------------------------------------------------------


def _picture_xml(rel_id: str, shape_id: int) -> str:
    """A one-pixel inline picture whose image is linked (``r:link``), not embedded."""
    from docx.oxml.ns import nsdecls

    return (
        f'<w:r {nsdecls("w", "wp", "a", "pic", "r")}><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{PIXEL_EMU}" cy="{PIXEL_EMU}"/>'
        f'<wp:docPr id="{shape_id}" name="Picture {shape_id}"/>'
        f'<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="0" name="p.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:link="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{PIXEL_EMU}" cy="{PIXEL_EMU}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        f"</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
    )


def add_docx_canary(docx_bytes: bytes, url: str) -> bytes:
    """Add a linked one-pixel picture whose image Word fetches from ``url`` on open.

    The main document part gets an image relationship with ``TargetMode="External"`` and
    the last body paragraph gets an inline picture that references it with ``r:link``
    (no embedded image data). The visible text and its layout stay unchanged.
    """
    import docx
    from docx.oxml import parse_xml

    d = docx.Document(io.BytesIO(docx_bytes))
    part = d.part
    rel_id = part.relate_to(url, _REL_IMAGE, is_external=True)
    paragraph = d.paragraphs[-1] if d.paragraphs else d.add_paragraph()
    paragraph._p.append(parse_xml(_picture_xml(rel_id, part.next_id)))
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def _read_rels(zf: zipfile.ZipFile) -> list[bytes]:
    """Contents of the package's .rels parts, skipping parts larger than MAX_RELS_BYTES."""
    infos = sorted((i for i in zf.infolist() if i.filename.endswith(".rels")), key=lambda i: i.filename)
    out = []
    for info in infos[:MAX_RELS_PARTS]:
        if info.file_size > MAX_RELS_BYTES:
            continue
        with zf.open(info) as fh:
            blob = fh.read(MAX_RELS_BYTES + 1)  # bounded even if the declared size lies
        if len(blob) <= MAX_RELS_BYTES:
            out.append(blob)
    return out


def _docx_hosts(data: bytes) -> list[str]:
    """Hosts of external image relationships in any part of the package.

    A .rels part that is not well-formed XML is skipped (Word would not use it either).
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            parts = _read_rels(zf)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, RuntimeError,
            NotImplementedError, ValueError, zlib.error) as exc:
        raise ValueError("berkas DOCX tidak dapat dibaca") from exc
    hosts = []
    for blob in parts:
        try:
            root = etree.fromstring(blob, parser)
        except etree.XMLSyntaxError:
            continue
        for rel in root.iter(f"{{{_REL_NS}}}Relationship"):
            if rel.get("TargetMode") == "External" and rel.get("Type", "").endswith("/image"):
                host = _host(rel.get("Target", ""))
                if host:
                    hosts.append(host)
    return hosts


def find_canary_hosts(data: bytes, kind: str) -> list[str]:
    """Host names a fetching viewer would look up when opening the file (deduplicated).

    ``kind`` is ``"pdf"`` (URI actions run on open) or ``"docx"`` (linked images).
    Ordinary hyperlinks are ignored because viewers do not fetch them on their own.
    Safe on untrusted files: a file that cannot be parsed raises ValueError with an
    Indonesian message, and reading is bounded (see MAX_ACTIONS and MAX_RELS_BYTES).
    """
    if kind == "pdf":
        hosts = _pdf_hosts(data)
    elif kind == "docx":
        hosts = _docx_hosts(data)
    else:
        raise ValueError(f"jenis berkas tidak didukung untuk kanari: {kind!r}")
    return list(dict.fromkeys(hosts))


def find_canary_tokens(data: bytes, kind: str, domain: str) -> list[str]:
    """Canary tokens of ``domain`` referenced by the file (useful as trace evidence)."""
    tokens = (token_from_qname(h, domain) for h in find_canary_hosts(data, kind))
    return [t for t in tokens if t]
