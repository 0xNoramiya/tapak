"""Shared setup of the printed-copy measurements: one issuance per background profile, paths.

The sample nota dinas is issued once per profile ("layar", the default background, and
"cetak", the print profile) for N = 100 fictitious recipients with the fixed test secret
(c = 3, eps = 1e-6, eps1 = 1e-8, m = 3273); copies 1 to 20 are printed and photographed.
Copy ids are random at issuance, so a new issuance has new codewords; set
CETAK_ISSUED_LAYAR or CETAK_ISSUED_CETAK to reuse an existing issuance folder (with
manifest.json and the copies). Results go to $CETAK_OUT (default out/cetak).

Run from the repository root: PYTHONPATH=. python -m scripts.cetak.<script>
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("CETAK_OUT", str(ROOT / "out" / "cetak")))
SAMPLE = ROOT / "samples" / "nota_dinas.pdf"
SECRET = bytes(range(32))       # the fixed test secret of tests/conftest.py
N_COPIES = 100                  # eps1 = 1e-8, m = 3273 (the README's headline configuration)
TEST_SEQS = list(range(1, 21))  # copies that are printed and photographed


def issued_dir(profile: str) -> Path:
    """Folder of the issuance for a background profile ("layar" or "cetak")."""
    env = os.environ.get(f"CETAK_ISSUED_{profile.upper()}")
    return Path(env) if env else OUT / f"issued-{profile}"


def ensure_issued(profile: str) -> Path:
    """Issue N_COPIES copies of the sample with the profile's background, once (no canary, no registry)."""
    from tapak.marker.background import background_profile
    from tapak.marker.issue import IssueSettings, Recipient, issue

    out = issued_dir(profile)
    if (out / "manifest.json").exists():
        return out
    recipients = [Recipient(f"R{i:03d}", f"Penerima Fiktif {i}", "Jabatan", "Satuan Uji")
                  for i in range(1, N_COPIES + 1)]
    issue(SAMPLE, recipients, out, SECRET,
          IssueSettings(n_max=N_COPIES, workers=4, background=background_profile(profile)), issuer="cetak-exp")
    return out


@lru_cache(maxsize=2)
def context(profile: str):
    """Trace context (master, plan, all 100 codewords) of a profile's issuance."""
    from tapak.decoder.trace import load_context
    from tapak.marker.issue import IssueManifest

    out = ensure_issued(profile)
    manifest = IssueManifest.from_json((out / "manifest.json").read_text(encoding="utf-8"))
    return load_context(SAMPLE.read_bytes(), manifest, SECRET)


def copy_pdf(profile: str, seq: int) -> bytes:
    """The PDF of copy ``seq`` (1-based) of a profile's issuance."""
    c = context(profile).manifest.copies[seq - 1]
    return (issued_dir(profile) / c.file).read_bytes()
