"""Local GGUF model (7 to 8B, Indonesian-capable) through llama.cpp.

Two ways to reach the model, both on this machine only:

1. in process with ``llama_cpp`` (llama-cpp-python) when a model path is configured
   (argument ``model_path`` or environment variable ``TAPAK_LLM_MODEL``). A configured
   model path without the library is an error, never a silent switch to the server;
2. otherwise over HTTP to a local ``llama-server`` (default
   http://127.0.0.1:8080/completion).

Any server URL that is not loopback (127.0.0.0/8, ::1, localhost) is refused, as is any
URL with user information ("user@host") or a backslash, so the check never depends on two
URL parsers agreeing. HTTP proxies are bypassed and redirects are not followed, so a
misconfiguration can never send document text to another host. Prompts and answers are
never logged. Failures reach the user as RuntimeError with an Indonesian message.

The answer format is plain numbered lines ("1. ...") for paraphrases and "YA: alasan" or
"TIDAK: alasan" for the equivalence judge; the parsers below are tolerant of small
deviations and simply skip lines they do not understand.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tapak.llm.provider import LLMProvider, protected_tokens

DEFAULT_SERVER_URL = "http://127.0.0.1:8080/completion"
MODEL_ENV = "TAPAK_LLM_MODEL"

_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[.)]\s*(.+?)\s*$")
_QUOTES = "\"'`\u201c\u201d\u2018\u2019"
_JUDGE = re.compile(r"^\W*(YA|TIDAK)\b\W*(.*)$", re.IGNORECASE)


def validate_local_url(url: str) -> str:
    """Return ``url`` if it is http(s) to a loopback host, else raise ValueError."""
    try:
        parts = urllib.parse.urlsplit(url)
        _ = parts.port  # raises ValueError for a malformed port
    except ValueError as exc:
        raise ValueError(f"alamat server LLM tidak valid: {url!r}") from exc
    if parts.scheme not in ("http", "https"):
        raise ValueError("alamat server LLM harus memakai http atau https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc or "\\" in url:
        raise ValueError("alamat server LLM tidak boleh memuat nama pengguna, '@', atau garis miring terbalik")
    host = parts.hostname or ""
    if host == "localhost":
        return url
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError(
            f"server LLM harus berada di mesin ini (127.0.0.1, ::1, atau localhost), bukan {host or url!r}"
        )
    return url


def build_paraphrase_prompt(sentence: str, n: int) -> str:
    """Indonesian instruction asking for ``n`` numbered paraphrases of ``sentence``."""
    return (
        "Anda adalah penyunting naskah dinas berbahasa Indonesia.\n"
        f"Tuliskan {n} parafrase dari kalimat di bawah ini dengan makna yang sama persis.\n"
        "Aturan:\n"
        "- pertahankan semua angka, nama, jabatan, satuan, waktu, dan kata berhuruf kapital apa adanya;\n"
        "- jangan menambah atau menghapus informasi, perintah, larangan, maupun kata ingkar;\n"
        "- gunakan bahasa dinas yang baku dengan panjang kalimat yang hampir sama;\n"
        "- tulis satu parafrase per baris dengan nomor 1., 2., dan seterusnya, tanpa penjelasan.\n"
        "\n"
        f"Kalimat: {sentence}\n"
        "\n"
        "Parafrase:\n"
    )


def build_judge_prompt(original: str, candidate: str) -> str:
    """Indonesian instruction asking whether ``candidate`` means exactly ``original``."""
    return (
        "Anda adalah pemeriksa kesetaraan makna naskah dinas berbahasa Indonesia.\n"
        "Apakah kalimat B bermakna sama persis dengan kalimat A, tanpa menambah, menghapus, "
        "atau mengubah informasi, angka, nama, waktu, perintah, larangan, maupun kata ingkar?\n"
        "Jawab dalam satu baris: YA atau TIDAK, lalu titik dua dan alasan singkat.\n"
        "\n"
        f"A: {original}\n"
        f"B: {candidate}\n"
        "\n"
        "Jawaban:"
    )


def parse_numbered_lines(text: str, limit: int | None = None) -> list[str]:
    """Items of a numbered list ("1. ...", "2) ..."), unquoted, deduplicated, in order.

    Markdown emphasis that chat-tuned models like to add ("**...**", "_..._") is removed.
    """
    out: list[str] = []
    for line in text.splitlines():
        m = _NUMBERED.match(line)
        if not m:
            continue
        item = " ".join(m.group(2).replace("*", "").strip().strip(_QUOTES + "_").split())
        if item and item not in out:
            out.append(item)
    return out if limit is None else out[:limit]


def parse_judge_answer(text: str) -> tuple[bool, str]:
    """Read "YA: ..." or "TIDAK: ..." from the first non-empty line; unreadable means not equivalent."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    m = _JUDGE.match(lines[0]) if lines else None
    if m is None:
        return False, "jawaban pemeriksa tidak dapat dibaca"
    ok = m.group(1).upper() == "YA"
    reason = m.group(2).strip() or ("setara" if ok else "tidak setara")
    return ok, reason


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: a local server must not bounce requests to another host."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:  # type: ignore[override]
        return None


class LlamaCppProvider(LLMProvider):
    """Paraphrases and equivalence judgements from a local llama.cpp model."""

    name = "llamacpp"

    def __init__(
        self,
        model_path: str | os.PathLike[str] | None = None,
        server_url: str = DEFAULT_SERVER_URL,
        n_ctx: int = 2048,
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout: float = 120.0,
    ) -> None:
        self.server_url = validate_local_url(server_url)
        env_path = os.environ.get(MODEL_ENV)
        self.model_path = Path(model_path) if model_path else (Path(env_path) if env_path else None)
        if self.model_path is not None and importlib.util.find_spec("llama_cpp") is None:
            raise RuntimeError(
                "pustaka llama_cpp tidak terpasang; pasang llama-cpp-python, atau kosongkan jalur model "
                "dan jalankan server llama.cpp lokal"
            )
        self.n_ctx = n_ctx
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._llama: object | None = None

    @property
    def uses_library(self) -> bool:
        """True if completions run in process with llama-cpp-python (a model path is configured)."""
        return self.model_path is not None

    def _complete_library(self, prompt: str, temperature: float) -> str:
        if self._llama is None:
            assert self.model_path is not None
            if not self.model_path.is_file():
                raise FileNotFoundError(f"berkas model GGUF tidak ditemukan: {self.model_path}")
            from llama_cpp import Llama  # optional dependency

            self._llama = Llama(model_path=str(self.model_path), n_ctx=self.n_ctx, verbose=False)
        out = self._llama(prompt, max_tokens=self.max_tokens, temperature=temperature)  # type: ignore[operator]
        return str(out["choices"][0]["text"])

    def _complete_http(self, prompt: str, temperature: float) -> str:
        payload = json.dumps(
            {"prompt": prompt, "n_predict": self.max_tokens, "temperature": temperature,
             "cache_prompt": False}
        ).encode("utf-8")
        req = urllib.request.Request(
            validate_local_url(self.server_url), data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:  # also raised for a refused redirect
            raise RuntimeError(f"server LLM lokal di {self.server_url} menolak permintaan (HTTP {exc.code})") from exc
        except (urllib.error.URLError, OSError) as exc:  # refused connection, timeout, ...
            raise RuntimeError(f"server LLM lokal tidak dapat dihubungi di {self.server_url}") from exc
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("jawaban server LLM lokal tidak dapat dibaca") from exc
        if not isinstance(body, dict):
            raise RuntimeError("jawaban server LLM lokal tidak dapat dibaca")
        return str(body.get("content", ""))

    def complete(self, prompt: str, temperature: float | None = None) -> str:
        """Raw completion of ``prompt`` from the local model."""
        t = self.temperature if temperature is None else temperature
        if self.uses_library:
            return self._complete_library(prompt, t)
        return self._complete_http(prompt, t)

    def paraphrase(self, sentence: str, n: int) -> list[str]:
        """Up to ``n`` numbered paraphrases from the model, the original removed."""
        if n <= 0:
            return []
        original = " ".join(sentence.split())
        items = parse_numbered_lines(self.complete(build_paraphrase_prompt(original, n)), limit=n)
        return [c for c in items if c != original]

    def judge_equivalent(self, original: str, candidate: str) -> tuple[bool, str]:
        """Protected-token check first (cheap, exact), then the model's YA/TIDAK verdict."""
        if protected_tokens(original) != protected_tokens(candidate):
            return False, "token terlindungi (angka, nama, atau kata kunci) berubah"
        answer = self.complete(build_judge_prompt(original, candidate), temperature=0.0)
        return parse_judge_answer(answer)
