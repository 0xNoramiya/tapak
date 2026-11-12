"""TAPAK_WORKERS: one cap on the worker processes of every issuance (CLI, web, demo) and on the
traces the web runs at once; validated with an Indonesian message. Fictional samples only."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tapak import cli, config
from tapak.config import pool_size, worker_limit
from tapak.marker import issue as issue_mod
from tapak.marker.issue import IssueSettings, issue, issue_workers, read_recipients
from tests_support import RECIPIENTS, ROOT, SAMPLE

SECRET = bytes(range(32))
BAD_VALUES = ["0", "-2", "abc", "2.5", "3 proses", "\u0663"]  # the last: ARABIC-INDIC DIGIT THREE


@pytest.fixture()
def cpus16(monkeypatch):
    """A machine (or container) where 16 CPUs are visible."""
    monkeypatch.delenv("TAPAK_WORKERS", raising=False)
    monkeypatch.setattr(config, "available_cpus", lambda: 16)


class FakePool:
    """ProcessPoolExecutor stand-in: records max_workers and renders in this process."""

    sizes: list[int] = []

    def __init__(self, max_workers, mp_context=None, initializer=None, initargs=()):
        FakePool.sizes.append(max_workers)
        initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, jobs):
        return map(fn, jobs)


@pytest.fixture()
def fake_pool(monkeypatch):
    FakePool.sizes = []
    monkeypatch.setattr(issue_mod, "ProcessPoolExecutor", FakePool)
    monkeypatch.setattr(issue_mod, "_main_importable", lambda: True)
    return FakePool


def test_worker_limit_reads_a_positive_integer(monkeypatch):
    monkeypatch.delenv("TAPAK_WORKERS", raising=False)
    assert worker_limit() is None
    for raw, value in (("3", 3), (" 2 ", 2), ("1", 1), ("", None), ("  ", None)):
        monkeypatch.setenv("TAPAK_WORKERS", raw)
        assert worker_limit() == value


@pytest.mark.parametrize("raw", BAD_VALUES)
def test_worker_limit_refuses_anything_else(monkeypatch, raw):
    monkeypatch.setenv("TAPAK_WORKERS", raw)
    with pytest.raises(ValueError, match="TAPAK_WORKERS harus bilangan bulat positif"):
        worker_limit()
    with pytest.raises(ValueError, match="TAPAK_WORKERS harus bilangan bulat positif"):
        pool_size(20)


def test_pool_size_caps_every_choice(cpus16, monkeypatch):
    assert pool_size(20) == 8                 # automatic: the CPUs, at most 8
    assert pool_size(3) == 3                  # never more than the jobs
    assert pool_size(20, requested=12) == 12  # an explicit --workers
    monkeypatch.setenv("TAPAK_WORKERS", "3")
    assert pool_size(20) == 3
    assert pool_size(20, requested=12) == 3   # the cap holds for --workers too
    assert pool_size(20, requested=2) == 2
    assert pool_size(2) == 2
    monkeypatch.setenv("TAPAK_WORKERS", "64")
    assert pool_size(20) == 8                 # the cap only lowers
    monkeypatch.setattr(config, "available_cpus", lambda: 1)
    monkeypatch.delenv("TAPAK_WORKERS")
    assert pool_size(20) == 1 and pool_size(0) == 1


def test_available_cpus_follows_the_affinity_mask(monkeypatch):
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 3}, raising=False)
    assert config.available_cpus() == 2
    monkeypatch.delattr(os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 6)
    assert config.available_cpus() == 6


def test_issue_starts_no_more_processes_than_the_cap(cpus16, fake_pool, monkeypatch, tmp_path):
    recipients = read_recipients(RECIPIENTS)[:5]
    monkeypatch.setenv("TAPAK_WORKERS", "2")
    m = issue(SAMPLE, recipients, tmp_path / "a", SECRET, IssueSettings())
    assert fake_pool.sizes == [2] and len(m.copies) == 5
    issue(SAMPLE, recipients, tmp_path / "b", SECRET, IssueSettings(workers=4))
    assert fake_pool.sizes == [2, 2]
    monkeypatch.delenv("TAPAK_WORKERS")
    issue(SAMPLE, recipients, tmp_path / "c", SECRET, IssueSettings())
    assert fake_pool.sizes == [2, 2, 5]  # without the cap: the CPUs, at most the copies
    assert issue_workers(5, 1) == 1


class CountingPool(FakePool):
    """FakePool that records the most worker processes of all pools running at once."""

    running = most = 0
    guard = threading.Lock()

    def __init__(self, max_workers, mp_context=None, initializer=None, initargs=()):
        self.size = max_workers
        super().__init__(max_workers, mp_context, initializer, initargs)

    def __enter__(self):
        with CountingPool.guard:
            CountingPool.running += self.size
            CountingPool.most = max(CountingPool.most, CountingPool.running)
        return self

    def __exit__(self, *exc):
        with CountingPool.guard:
            CountingPool.running -= self.size
        return False


@pytest.mark.parametrize("cap", ["1", "2"])
def test_concurrent_issuances_in_one_process_never_mix_or_exceed_the_cap(cpus16, monkeypatch, tmp_path, cap):
    """The web server issues for several sessions at once (one thread each). Their rendering
    takes turns: one process never runs more than TAPAK_WORKERS workers, and copies rendered in
    the process itself (TAPAK_WORKERS=1) never use the document of another issuance."""
    CountingPool.running = CountingPool.most = 0
    monkeypatch.setattr(issue_mod, "ProcessPoolExecutor", CountingPool)
    monkeypatch.setattr(issue_mod, "_main_importable", lambda: True)
    monkeypatch.setenv("TAPAK_WORKERS", cap)
    both_ready = threading.Event()
    inits, seen = [], []
    real_init, real_render = issue_mod._worker_init, issue_mod._render_one

    def init(*args, **kwargs):
        real_init(*args, **kwargs)
        inits.append(1)
        if len(inits) >= 2:
            both_ready.set()

    def render(job):
        both_ready.wait(3)  # without turns, the other issuance replaces the state here
        seen.append((Path(job[2]).parent.name, issue_mod._W["master"].doc_hash))
        return real_render(job)

    monkeypatch.setattr(issue_mod, "_worker_init", init)
    monkeypatch.setattr(issue_mod, "_render_one", render)
    recipients = read_recipients(RECIPIENTS)[:3]
    docs = {"a": SAMPLE, "b": ROOT / "samples" / "surat_telegram.pdf"}
    results, errors = {}, []

    def run(name):
        try:
            results[name] = issue(docs[name], recipients, tmp_path / name, SECRET, IssueSettings())
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(name,)) for name in docs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    expected = {name: results[name].doc_hash for name in docs}
    assert len(seen) == 6 and all(doc == expected[name] for name, doc in seen), seen
    if cap == "2":
        assert CountingPool.most == 2


def test_issue_refuses_a_bad_cap_before_any_work(monkeypatch, tmp_path):
    monkeypatch.setenv("TAPAK_WORKERS", "nol")
    with pytest.raises(ValueError, match="TAPAK_WORKERS harus bilangan bulat positif"):
        issue(SAMPLE, read_recipients(RECIPIENTS)[:2], tmp_path / "out", SECRET, IssueSettings(workers=1))
    assert not (tmp_path / "out").exists()


def test_service_refuses_a_bad_cap_before_the_workspace(monkeypatch, tmp_path):
    from tapak.config import load_settings
    from tapak.service import issue_document

    monkeypatch.setenv("TAPAK_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TAPAK_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("TAPAK_WORKERS", "0")
    with pytest.raises(ValueError, match="TAPAK_WORKERS harus bilangan bulat positif"):
        issue_document(load_settings(), SAMPLE, read_recipients(RECIPIENTS)[:2], IssueSettings(), "uji")
    assert not (tmp_path / "data").exists() and not (tmp_path / "keys").exists()


def _cli(tmp_path, *argv):
    return cli.main(["--data", str(tmp_path / "data"), "--keys", str(tmp_path / "keys"), *argv])


def test_cli_issue_names_its_process_count_and_honours_the_cap(cpus16, fake_pool, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TAPAK_CANARY_DOMAIN", raising=False)
    roster = tmp_path / "penerima.csv"
    roster.write_text("".join(RECIPIENTS.read_text(encoding="utf-8").splitlines(keepends=True)[:5]), encoding="utf-8")
    assert _cli(tmp_path, "keys", "init") == 0
    monkeypatch.setenv("TAPAK_WORKERS", "2")
    capsys.readouterr()
    assert _cli(tmp_path, "issue", str(SAMPLE), str(roster), "--workers", "6", "--no-registry") == 0
    out = capsys.readouterr().out
    assert "Catatan: --workers 6 dibatasi TAPAK_WORKERS=2" in out
    assert "4 salinan ditulis" in out and "(2 proses)" in out and fake_pool.sizes == [2]


def test_cli_refuses_a_bad_cap_and_a_bad_workers_option(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TAPAK_WORKERS", "abc")
    assert _cli(tmp_path, "issue", str(SAMPLE), str(RECIPIENTS)) == 2
    err = capsys.readouterr().err
    assert "galat: TAPAK_WORKERS harus bilangan bulat positif" in err and "'abc'" in err
    assert not (tmp_path / "data").exists()
    monkeypatch.delenv("TAPAK_WORKERS")
    for bad in ("0", "-1", "dua"):
        with pytest.raises(SystemExit) as exc:
            _cli(tmp_path, "issue", str(SAMPLE), str(RECIPIENTS), "--workers", bad)
        assert exc.value.code == 1
        assert f"--workers harus bilangan bulat positif, bukan '{bad}'" in capsys.readouterr().err


def test_cli_web_and_demo_check_the_cap_before_starting(monkeypatch, tmp_path, capsys):
    import uvicorn

    def never(*args, **kwargs):
        raise AssertionError("server tidak boleh dijalankan")

    monkeypatch.setattr(uvicorn, "run", never)
    monkeypatch.setenv("TAPAK_WORKERS", "-1")
    assert _cli(tmp_path, "web") == 2
    assert "galat: TAPAK_WORKERS harus bilangan bulat positif" in capsys.readouterr().err
    assert _cli(tmp_path, "demo", "--workdir", str(tmp_path / "demo")) == 2
    assert "TAPAK_WORKERS" in capsys.readouterr().err and not (tmp_path / "demo").exists()


def test_trace_slots_follow_the_worker_limit_and_the_memory():
    from tapak.config import TRACE_MEMORY_MB, total_memory_mb, trace_slots

    assert trace_slots(None, None) == 2 and trace_slots(8, None) == 2 and trace_slots(1, None) == 1
    assert trace_slots(None, 2 * TRACE_MEMORY_MB) == 2
    assert trace_slots(None, 2 * TRACE_MEMORY_MB - 1) == 1 and trace_slots(None, 1960) == 1  # a 2 GB host
    assert trace_slots(None, 3900) == 2  # a 4 GB host
    assert trace_slots(None, 100) == 1 and trace_slots(1, 64_000) == 1
    total = total_memory_mb()
    assert total is None or total > 100


def _import_web(value: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "TAPAK_WORKERS"}
    env["PYTHONPATH"] = str(ROOT)
    if value is not None:
        env["TAPAK_WORKERS"] = value
    return subprocess.run([sys.executable, "-c", "import tapak.web.app as a; print(a.TRACE_SLOTS)"],
                          env=env, capture_output=True, text=True, timeout=120)


def test_web_server_caps_traces_and_stops_on_a_bad_value():
    """uvicorn tapak.web.app:app (the container's command) reads TAPAK_WORKERS when it starts."""
    from tapak.config import total_memory_mb, trace_slots

    two = str(trace_slots(None, total_memory_mb()))  # "2", or "1" on a host too small for two traces
    assert _import_web(None).stdout.strip() == two
    assert _import_web("1").stdout.strip() == "1"
    assert _import_web("8").stdout.strip() == two
    bad = _import_web("2,5")
    assert bad.returncode == 1 and "Traceback" not in bad.stderr and not bad.stdout
    assert ("galat: TAPAK_WORKERS harus bilangan bulat positif (jumlah proses kerja paling banyak), bukan '2,5'"
            in bad.stderr)
