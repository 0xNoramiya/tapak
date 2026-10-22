"""requirements.lock: the Docker image installs exactly the pinned runtime dependencies of TAPAK
(scripts/kunci_versi.py, make kunci-versi), and pyproject.toml stays the place of the ranges that
`pip install -e .[dev]` resolves."""

from __future__ import annotations

import importlib.util
import re
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from tests_support import ROOT

LOCK = ROOT / "requirements.lock"
PIN = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)==([0-9][0-9A-Za-z.+!-]*)")


def _script():
    spec = importlib.util.spec_from_file_location("kunci_versi", ROOT / "scripts" / "kunci_versi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pins() -> dict[str, str]:
    pins = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        m = PIN.fullmatch(text)
        assert m, f"baris kunci tidak sah: {line!r}"
        assert m.group(1) not in pins, f"pustaka ganda: {m.group(1)}"
        pins[m.group(1)] = m.group(2)
    return pins


def test_every_runtime_dependency_is_pinned_within_its_range():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = _pins()
    assert list(pins) == sorted(pins) and all(canonicalize_name(n) == n for n in pins)
    for text in project["dependencies"]:
        req = Requirement(text)
        name = canonicalize_name(req.name)
        assert name in pins, f"{name} tidak ada di requirements.lock"
        assert req.specifier.contains(pins[name], prereleases=True), f"{name}=={pins[name]} di luar {req.specifier}"


def test_no_development_or_optional_tools_in_the_image():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = _pins()
    optional = {canonicalize_name(Requirement(r).name) for reqs in project["optional-dependencies"].values()
                for r in reqs}
    assert optional and not optional & set(pins), optional & set(pins)
    assert not {"pip", "setuptools", "wheel", "tapak"} & set(pins)


def test_dockerfile_installs_the_lock_without_resolving():
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY requirements.lock ./" in docker
    assert "pip install --no-cache-dir --no-deps --only-binary :all: -r requirements.lock" in docker
    assert "pip install --no-cache-dir --no-deps . && pip check" in docker
    ignored = {line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()}
    assert not ignored & {"requirements.lock", "*.lock"}


def test_generator_output_parses_back_to_its_pins():
    k = _script()
    found = {"fastapi": ("FastAPI", "0.1.0", {"pyproject.toml"}), "starlette": ("starlette", "1.2.3", {"fastapi"})}
    text = k.render(found)
    assert k.pins(text) == {"fastapi": "0.1.0", "starlette": "1.2.3"}
    assert "fastapi==0.1.0\n    # via pyproject.toml\n" in text and text.startswith("# Runtime dependencies")
    assert k.pins(LOCK.read_text(encoding="utf-8")) == _pins()
