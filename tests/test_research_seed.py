"""Research seed of the benchmark issuance (``tapak issue --benih-riset``, ``make photos``).

Ordinary issuance keeps drawing a fresh code secret and random copy ids; only an explicit
research seed fixes them, and it never touches a registry or an existing secret.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tapak.cli import main
from tapak.keys import (
    install_research_secret,
    load_code_secret,
    research_code_secret,
    research_copy_ids,
    research_seed_of,
)
from tapak.marker.issue import COPY_ID, check_copy_ids
from tests_support import RECIPIENTS, SAMPLE

N = 3


@pytest.fixture(scope="module")
def roster(tmp_path_factory) -> Path:
    """The first N fictional recipients of samples/recipients.csv (a short roster issues fast)."""
    path = tmp_path_factory.mktemp("roster") / "penerima.csv"
    path.write_text("".join(RECIPIENTS.read_text(encoding="utf-8").splitlines(keepends=True)[:N + 1]),
                    encoding="utf-8")
    return path


def _issue(root: Path, roster: Path, *extra: str) -> int:
    return main(["--data", str(root / "data"), "--keys", str(root / "keys"), "issue", str(SAMPLE), str(roster),
                 "--no-registry", "--canary-domain", "", "--workers", "1", *extra])


def _manifest(root: Path) -> dict:
    return json.loads(next((root / "data" / "dokumen").glob("*/manifest.json")).read_text(encoding="utf-8"))


def _secret(root: Path) -> bytes:
    return load_code_secret(root / "keys" / "code_secret.key")


def test_default_issuance_draws_random_ids_and_a_fresh_secret(tmp_path, roster, capsys):
    runs = [tmp_path / "a", tmp_path / "b"]
    for root in runs:
        assert _issue(root, roster) == 0
    assert "benih" not in capsys.readouterr().out
    ids = [[c["copy_id"] for c in _manifest(root)["copies"]] for root in runs]
    secrets = [_secret(root) for root in runs]
    assert secrets[0] != secrets[1]
    assert all(len(ids[k]) == N == len(set(ids[k])) and all(COPY_ID.fullmatch(c) for c in ids[k]) for k in (0, 1))
    assert not set(ids[0]) & set(ids[1])
    assert research_code_secret(2026) not in secrets and not set(ids[0]) & set(research_copy_ids(2026, N))
    assert all(research_seed_of(root / "keys" / "code_secret.key") is None for root in runs)


def test_research_seed_reproduces_ids_and_secret(tmp_path, roster, capsys):
    runs = [tmp_path / "a", tmp_path / "b"]
    for root in runs:
        assert _issue(root, roster, "--benih-riset", "2026") == 0
        out = capsys.readouterr().out
        assert "PERINGATAN: penerbitan riset" in out and "benih 2026" in out
    manifests = [_manifest(root) for root in runs]
    for m, root in zip(manifests, runs):
        assert [c["copy_id"] for c in m["copies"]] == research_copy_ids(2026, N)
        assert _secret(root) == research_code_secret(2026)
        assert research_seed_of(root / "keys" / "code_secret.key") == 2026
    # Same secret and ids: same codewords, so the same code commitments.
    assert [c["code_digest"] for c in manifests[0]["copies"]] == [c["code_digest"] for c in manifests[1]["copies"]]
    # Another seed gives another secret and other ids.
    assert research_code_secret(2027) != research_code_secret(2026)
    assert not set(research_copy_ids(2027, N)) & set(research_copy_ids(2026, N))
    assert research_copy_ids(2026, N + 2)[:N] == research_copy_ids(2026, N)


def test_research_seed_needs_no_registry_and_never_replaces_a_secret(tmp_path, roster, capsys):
    plain = tmp_path / "biasa"
    assert main(["--data", str(plain / "data"), "--keys", str(plain / "keys"), "issue", str(SAMPLE),
                 str(roster), "--benih-riset", "2026"]) == 2
    assert "--no-registry" in capsys.readouterr().err
    assert not (plain / "keys").exists() and not (plain / "data").exists()

    real = tmp_path / "nyata"
    assert main(["--keys", str(real / "keys"), "keys", "init", "--no-signing-key"]) == 0
    before = (real / "keys" / "code_secret.key").read_bytes()
    assert _issue(real, roster, "--benih-riset", "2026") == 2
    assert "rahasia kode lain" in capsys.readouterr().err
    assert (real / "keys" / "code_secret.key").read_bytes() == before
    assert research_seed_of(real / "keys" / "code_secret.key") is None
    assert not (real / "data" / "dokumen").exists() or not any((real / "data" / "dokumen").glob("*/manifest.json"))

    with pytest.raises(ValueError, match="tidak negatif"):
        install_research_secret(tmp_path / "k" / "code_secret.key", -1)


def test_ordinary_issuance_refuses_a_research_key_folder(tmp_path, roster, capsys):
    """A public research secret must never mark a real document, even by a later plain issue."""
    root = tmp_path / "riset"
    install_research_secret(root / "keys" / "code_secret.key", 7)
    assert _issue(root, roster) == 2
    assert "benih riset 7" in capsys.readouterr().err
    assert not (root / "data" / "dokumen").exists() or not any((root / "data" / "dokumen").glob("*/manifest.json"))


def test_fixed_copy_ids_are_checked():
    check_copy_ids(research_copy_ids(1, 3), 3)
    for ids, msg in ((research_copy_ids(1, 2), "tidak sama"), (["0123456789ABCDEF"] * 1, "heksadesimal"),
                     (["0123456789abcdef"] * 2, "ganda"), (["123"], "heksadesimal")):
        with pytest.raises(ValueError, match=msg):
            check_copy_ids(ids, len(ids) if msg != "tidak sama" else 3)
