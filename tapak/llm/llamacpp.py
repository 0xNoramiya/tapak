"""Local GGUF instruct model (Indonesian-capable) through llama.cpp.

Two ways to reach the model, both on this machine only:

1. in process with ``llama_cpp`` (llama-cpp-python) when a model path is configured
   (argument ``model_path`` or environment variable ``TAPAK_LLM_MODEL``). A configured
   model path without the library is an error, never a silent switch to the server;
2. otherwise over HTTP to a local ``llama-server`` (default http://127.0.0.1:8080).

Both ways send the prompt as a chat message, so the model's own chat template is applied.
Instruct models answer a bare prompt (llama-server ``/completion``) by continuing the
text: with Qwen2.5-3B-Instruct the judge echoed its own instruction ("TIDAK, lalu titik
dua ...") and rejected every candidate. The server URL may name the server
(``http://127.0.0.1:8080``) or, as in older configurations, its ``/completion`` or
``/v1/chat/completions`` path; requests always go to ``/v1/chat/completions``.

Any server URL that is not loopback (127.0.0.0/8, ::1, localhost) is refused, as is any
URL with user information ("user@host") or a backslash, so the check never depends on two
URL parsers agreeing. HTTP proxies are bypassed and redirects are not followed. Before the
first document sentence is sent, the server must answer ``GET /v1/models`` with a model
list: a loopback port can be forwarded into a container or held by an unrelated local
service (llama-server's default port changed from 8080 to 9931 in v0.7.0, and 8080 is a
common port), and that service must not receive document text. Prompts and answers are
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

DEFAULT_SERVER_URL = "http://127.0.0.1:8080"
MODEL_ENV = "TAPAK_LLM_MODEL"
TIMEOUT_ENV = "TAPAK_LLM_TIMEOUT"
DEFAULT_TIMEOUT = 120.0     # seconds per request; a 3B model on 4 busy CPU cores can need more
CHAT_PATH = "/v1/chat/completions"
MODELS_PATH = "/v1/models"
# Paths accepted at the end of a configured server URL; the server base is what precedes them.
_ENDPOINT_SUFFIXES = (CHAT_PATH, "/v1/completions", "/completion", "/completions", "/v1")
JUDGE_MAX_TOKENS = 64       # "YA: alasan singkat" needs about 20 to 40 tokens

_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[.)]\s*(.+?)\s*$")
_ENUMERATOR = re.compile(r"^\d{1,2}\s*[.)]\s+")
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


def server_base(url: str) -> str:
    """Scheme, host and base path of a (validated) server URL, without a known endpoint path."""
    parts = urllib.parse.urlsplit(validate_local_url(url))
    path = parts.path.rstrip("/")
    for suffix in _ENDPOINT_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def build_paraphrase_prompt(sentence: str, n: int) -> str:
    """Indonesian instruction asking for ``n`` numbered paraphrases of ``sentence``.

    The model is asked to exchange one or two words or phrases for their usual equivalents
    and keep the sentence structure. A variant must fit exactly the rows of the original,
    and free rewording (the earlier prompt) gave rewrites that did not fit, dropped the
    letter formulas ("Dengan hormat", "Demikian") or added content. With Gemma 3 4B on the
    held-out surat_telegram.pdf (2 sentences, 3 generations each) the earlier prompt gave 0
    variants a human could approve and this one 2 (Qwen2.5-3B with this prompt: 3); on
    nota_dinas.pdf neither prompt gave any (scripts/llm_eval.py).
    """
    return (
        "Anda adalah penyunting naskah dinas berbahasa Indonesia.\n"
        f"Tuliskan {n} parafrase dari kalimat di bawah ini. Setiap parafrase hanya mengganti satu "
        "atau dua kata atau frasa dengan padanannya yang lazim dalam surat dinas, sehingga maknanya "
        "tetap sama persis.\n"
        "Aturan:\n"
        "- pertahankan susunan kalimat; jangan menghapus kata lain dan jangan menambah keterangan baru;\n"
        "- pertahankan semua angka, nama, jabatan, satuan, waktu, dan kata berhuruf kapital apa adanya;\n"
        "- jangan menambah atau menghapus informasi, perintah, larangan, maupun kata ingkar;\n"
        "- jangan memakai tanda baca yang tidak ada pada kalimat asli;\n"
        "- setiap parafrase harus berbeda dari kalimat asli dan dari parafrase lainnya;\n"
        "- tulis satu parafrase per baris dengan nomor 1., 2., dan seterusnya, tanpa penjelasan.\n"
        "\n"
        f"Kalimat: {sentence}\n"
    )


def build_judge_prompt(original: str, candidate: str) -> str:
    """Indonesian instruction asking whether ``candidate`` keeps the content of ``original``.

    Synonyms and another word order are allowed explicitly. Asked whether B "means exactly
    the same", Qwen2.5-3B answered TIDAK to 9 of 12 known-equivalent pairs because some word
    differed; with this wording it accepted 12 of 12 (and 2 of 12 meaning-changing pairs;
    Gemma 3 4B: 12 of 12 and 2 of 12). The judge is a filter, not a guarantee: every
    variant still needs a human decision.
    """
    return (
        "Anda adalah pemeriksa naskah dinas berbahasa Indonesia.\n"
        "Kalimat B adalah usulan parafrase dari kalimat A. Parafrase boleh memakai sinonim atau "
        "susunan kata yang berbeda.\n"
        "Jawab YA bila B menyampaikan informasi dan maksud yang sama dengan A.\n"
        "Jawab TIDAK bila B menambah, menghapus, atau mengubah informasi, pelaku, sasaran, angka, nama, "
        "waktu, perintah, larangan, atau kata ingkar.\n"
        "Jawab dalam satu baris: YA atau TIDAK, lalu titik dua dan alasan singkat.\n"
        "\n"
        f"A: {original}\n"
        f"B: {candidate}\n"
        "\n"
        "Jawaban:"
    )


def parse_numbered_lines(text: str, limit: int | None = None) -> list[str]:
    """Items of a numbered list ("1. ...", "2) ..."), unquoted, deduplicated, in order.

    Markdown emphasis that chat-tuned models like to add ("**...**", "_..._") is removed,
    and so are repeated enumerators ("6. 1. kalimat", seen when a model restarts its list).
    """
    out: list[str] = []
    for line in text.splitlines():
        m = _NUMBERED.match(line)
        if not m:
            continue
        item = m.group(2).replace("*", "").strip()
        while _ENUMERATOR.match(item):
            item = _ENUMERATOR.sub("", item, count=1)
        item = " ".join(item.strip(_QUOTES + "_ ").split())
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


def chat_answer(body: object) -> str:
    """Text of the first choice of an OpenAI-style chat completion; RuntimeError if absent."""
    try:
        content = body["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("jawaban server LLM lokal tidak dapat dibaca") from exc
    if content is None:
        return ""
    if not isinstance(content, str):
        raise RuntimeError("jawaban server LLM lokal tidak dapat dibaca")
    return content


def _env_timeout() -> float:
    """Request timeout from TAPAK_LLM_TIMEOUT (seconds), else DEFAULT_TIMEOUT."""
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not 1 <= value <= 3600:
        raise ValueError(f"{TIMEOUT_ENV} harus berupa jumlah detik antara 1 dan 3600, bukan {raw!r}")
    return value


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
        timeout: float | None = None,
    ) -> None:
        self.server_url = validate_local_url(server_url)
        self.base_url = server_base(server_url)
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
        self.timeout = timeout if timeout is not None else _env_timeout()
        self._llama: object | None = None
        self._server_checked = False

    @property
    def uses_library(self) -> bool:
        """True if completions run in process with llama-cpp-python (a model path is configured)."""
        return self.model_path is not None

    def _complete_library(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> str:
        if self._llama is None:
            assert self.model_path is not None
            if not self.model_path.is_file():
                raise FileNotFoundError(f"berkas model GGUF tidak ditemukan: {self.model_path}")
            from llama_cpp import Llama  # optional dependency

            self._llama = Llama(model_path=str(self.model_path), n_ctx=self.n_ctx, verbose=False)
        out = self._llama.create_chat_completion(  # type: ignore[attr-defined]
            messages=messages, max_tokens=max_tokens, temperature=temperature,
        )
        return chat_answer(out)

    def _request(self, path: str, payload: dict[str, object] | None) -> object:
        """JSON answer of the local server at ``base_url + path`` (POST if ``payload``, else GET)."""
        url = validate_local_url(self.base_url + path)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                     method="GET" if payload is None else "POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:  # also raised for a refused redirect
            raise RuntimeError(f"server LLM lokal di {self.base_url} menolak permintaan (HTTP {exc.code})") from exc
        except (urllib.error.URLError, OSError) as exc:  # refused connection, timeout, ...
            if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
                raise RuntimeError(
                    f"server LLM lokal di {self.base_url} tidak menjawab dalam {self.timeout:g} detik (model "
                    f"terlalu lambat atau mesin sibuk); naikkan {TIMEOUT_ENV} atau pakai model yang lebih kecil"
                ) from exc
            raise RuntimeError(f"server LLM lokal tidak dapat dihubungi di {self.base_url}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("jawaban server LLM lokal tidak dapat dibaca") from exc

    def check_server(self) -> None:
        """Make sure ``base_url`` serves an LLM (``GET /v1/models`` lists models) before any text is sent."""
        if self._server_checked:
            return
        try:
            body = self._request(MODELS_PATH, None)
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc}; pastikan TAPAK_LLM_URL menunjuk ke llama-server (GET {MODELS_PATH} harus menjawab)"
            ) from exc
        if not (isinstance(body, dict) and isinstance(body.get("data"), list) and body["data"]):
            raise RuntimeError(
                f"{self.base_url} bukan server LLM yang dikenali (GET {MODELS_PATH} tidak berisi daftar model); "
                "periksa TAPAK_LLM_URL"
            )
        self._server_checked = True

    def _complete_http(self, messages: list[dict[str, str]], temperature: float, max_tokens: int) -> str:
        self.check_server()
        body = self._request(CHAT_PATH, {
            "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
            "stream": False, "cache_prompt": False,
        })
        return chat_answer(body)

    def complete(self, prompt: str, temperature: float | None = None, max_tokens: int | None = None) -> str:
        """The model's answer to ``prompt`` sent as one user chat message."""
        t = self.temperature if temperature is None else temperature
        n = self.max_tokens if max_tokens is None else max_tokens
        messages = [{"role": "user", "content": prompt}]
        if self.uses_library:
            return self._complete_library(messages, t, n)
        return self._complete_http(messages, t, n)

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
        answer = self.complete(build_judge_prompt(original, candidate), temperature=0.0,
                               max_tokens=JUDGE_MAX_TOKENS)
        return parse_judge_answer(answer)
