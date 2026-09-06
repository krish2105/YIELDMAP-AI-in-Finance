"""The model provider chain.

One interface, several backends, tried in a fixed order that is free by construction:

    Ollama (local) -> Gemini (free tier) -> Groq (free tier) -> fake (recorded fixtures)

Anthropic is present in the code and switched off. Enabling it needs both a key and an explicit
opt-in, and the guard refuses by default, because the project's cost claim is a design property
rather than a promise: there is no configuration reachable by accident that spends money.

Falling through is the normal case, not an error path. This project is developed in an environment
with no Ollama and no route to Groq, so the chain routinely skips two tiers on its way to Gemini,
and skips all of them in CI. Every hop is recorded so the /data page can show which backend
actually answered, and the report can say honestly how often it degraded.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from rag.quota import QuotaExceeded, QuotaLedger

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "llm"

# The order is the policy. Free tiers first, local before remote, paid never.
DEFAULT_CHAIN = ("ollama", "gemini", "groq", "fake")


class ProviderUnavailable(RuntimeError):
    """This backend cannot answer right now; the chain should try the next one."""


@dataclass
class Completion:
    text: str
    backend: str
    elapsed_s: float
    degraded: bool = False
    note: str | None = None


@dataclass
class Embedding:
    vectors: list[list[float]]
    backend: str
    dimensions: int
    degraded: bool = False


class Backend(ABC):
    name: str = "base"

    # Whether this backend's requests count against a daily allowance. Quotas exist to protect
    # free *API* tiers from being spent; a backend that makes no network call has nothing to
    # protect, and metering one means a long session or a CI run silently degrades every answer
    # to a refusal once an imaginary limit is reached. That is exactly what happened.
    metered: bool = True

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """Whether this backend can be used, and why not when it cannot."""

    @abstractmethod
    def generate(
        self, prompt: str, *, system: str | None = None, max_tokens: int = 1024
    ) -> str: ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderUnavailable(f"{self.name} does not provide embeddings")


class OllamaBackend(Backend):
    """A local model. Free, private and usually absent from a cloud sandbox."""

    name = "ollama"
    metered = False

    def __init__(self) -> None:
        self.host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        self.model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

    def available(self) -> tuple[bool, str]:
        if shutil.which("ollama") is None:
            return False, "the ollama binary is not installed"
        try:
            listed = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"ollama could not be run: {type(exc).__name__}"
        if listed.returncode != 0:
            return False, "ollama is installed but not serving"
        return True, "local model available"

    def generate(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if system:
            payload["system"] = system
        with httpx.Client(timeout=120) as client:
            r = client.post(f"{self.host}/api/generate", json=payload)
            r.raise_for_status()
            return str(r.json().get("response", "")).strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        with httpx.Client(timeout=120) as client:
            for text in texts:
                r = client.post(
                    f"{self.host}/api/embeddings", json={"model": self.model, "prompt": text}
                )
                r.raise_for_status()
                out.append([float(v) for v in r.json()["embedding"]])
        return out


class GeminiBackend(Backend):
    """Google's free tier. The only remote tier reachable from this project's sandbox."""

    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self) -> None:
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.embed_model = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001")

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, "GEMINI_API_KEY is not set"
        return True, "free tier configured"

    def generate(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str:
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        with httpx.Client(timeout=120) as client:
            r = client.post(
                f"{self.BASE}/models/{self.model}:generateContent",
                params={"key": self.key},
                json=body,
            )
            if r.status_code == 429:
                raise QuotaExceeded("gemini returned 429: free-tier rate limit reached")
            r.raise_for_status()
            candidates = r.json().get("candidates") or []
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts") or []
            return "".join(p.get("text", "") for p in parts).strip()

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        with httpx.Client(timeout=120) as client:
            for text in texts:
                r = client.post(
                    f"{self.BASE}/models/{self.embed_model}:embedContent",
                    params={"key": self.key},
                    json={
                        "content": {"parts": [{"text": text}]},
                        # 768 is the widest pgvector's HNSW index supports; the model emits more
                        # by default and truncates cleanly.
                        "outputDimensionality": 768,
                    },
                )
                if r.status_code == 429:
                    raise QuotaExceeded("gemini returned 429: free-tier rate limit reached")
                r.raise_for_status()
                out.append([float(v) for v in r.json()["embedding"]["values"]])
        return out


class GroqBackend(Backend):
    """Groq's free tier. Unreachable from this sandbox; kept for the deployed environment."""

    name = "groq"
    BASE = "https://api.groq.com/openai/v1"

    def __init__(self) -> None:
        self.key = os.environ.get("GROQ_API_KEY", "").strip()
        self.model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, "GROQ_API_KEY is not set"
        return True, "free tier configured"

    def generate(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        with httpx.Client(timeout=120) as client:
            r = client.post(
                f"{self.BASE}/chat/completions",
                headers={"Authorization": f"Bearer {self.key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.2,
                },
            )
            if r.status_code == 429:
                raise QuotaExceeded("groq returned 429: free-tier rate limit reached")
            r.raise_for_status()
            return str(r.json()["choices"][0]["message"]["content"]).strip()


class AnthropicBackend(Backend):
    """Present, and off.

    Enabling this needs a key *and* ANTHROPIC_ENABLED=true. Two switches rather than one, because
    the project's zero-cost claim should not be one stray environment variable away from being
    false.
    """

    name = "anthropic"

    def available(self) -> tuple[bool, str]:
        if os.environ.get("ANTHROPIC_ENABLED", "false").strip().lower() != "true":
            return False, "the paid backend is switched off by policy"
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            return False, "ANTHROPIC_API_KEY is not set"
        return True, "explicitly enabled"

    def generate(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str:
        raise ProviderUnavailable(
            "the paid backend is present for completeness and is not wired up; this project runs "
            "on free tiers only"
        )


class FakeBackend(Backend):
    """Recorded fixtures, so the whole suite runs offline with no key and no quota.

    A fixture is keyed by the hash of its prompt, so a test that changes its prompt gets a fresh
    deterministic answer rather than silently reusing an unrelated one.
    """

    name = "fake"
    metered = False

    def __init__(self, fixture_dir: Path = FIXTURE_DIR) -> None:
        self.fixture_dir = fixture_dir

    def available(self) -> tuple[bool, str]:
        return True, "recorded fixtures need nothing"

    @staticmethod
    def _key(prompt: str) -> str:
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]

    def generate(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str:
        path = self.fixture_dir / f"{self._key(prompt)}.txt"
        if path.exists():
            return path.read_text().strip()
        # No fixture: answer deterministically from the prompt so behaviour is reproducible.
        return (
            "This answer comes from the offline fixture backend, which is used when no model "
            "provider is configured. It is deterministic and carries no factual claims."
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Deterministic pseudo-embeddings.

        Hash-derived rather than meaningful: they let the vector code paths, the caching and the
        fusion be exercised end to end without a network, while the lexical half of hybrid
        retrieval carries the actual relevance. Nothing downstream is allowed to mistake these for
        semantics — the retriever records that it degraded.
        """
        import numpy as np

        out: list[list[float]] = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            vector = rng.normal(0, 1, 768)
            vector /= np.linalg.norm(vector) or 1.0
            out.append([float(v) for v in vector])
        return out


BACKENDS: dict[str, type[Backend]] = {
    "ollama": OllamaBackend,
    "gemini": GeminiBackend,
    "groq": GroqBackend,
    "anthropic": AnthropicBackend,
    "fake": FakeBackend,
}


@dataclass
class LLMProvider:
    """The chain. Tries each backend in order and records every hop."""

    chain: tuple[str, ...] = DEFAULT_CHAIN
    ledger: QuotaLedger = field(default_factory=QuotaLedger)
    hops: list[dict[str, Any]] = field(default_factory=list)
    _instances: dict[str, Backend] = field(default_factory=dict, repr=False)

    @classmethod
    def from_env(cls, ledger: QuotaLedger | None = None) -> LLMProvider:
        """Build the chain from LLM_PROVIDER.

        Naming a backend starts the chain there and keeps the remaining fallbacks, except for
        'fake', which pins the offline backend so CI cannot accidentally reach the network.
        """
        preferred = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
        if preferred == "fake":
            chain: tuple[str, ...] = ("fake",)
        elif preferred in DEFAULT_CHAIN:
            start = DEFAULT_CHAIN.index(preferred)
            chain = DEFAULT_CHAIN[start:]
        elif preferred == "anthropic":
            chain = ("anthropic", "fake")
        else:
            chain = DEFAULT_CHAIN
        return cls(chain=chain, ledger=ledger or QuotaLedger())

    def _backend(self, name: str) -> Backend:
        if name not in self._instances:
            self._instances[name] = BACKENDS[name]()
        return self._instances[name]

    def describe(self) -> list[dict[str, Any]]:
        """Which backends could answer right now, and why the others cannot."""
        out = []
        for name in self.chain:
            backend = self._backend(name)
            ok, reason = backend.available()
            out.append(
                {
                    "backend": name,
                    "available": ok,
                    "reason": reason,
                    "requests_today": self.ledger.used(name),
                    # None rather than a number: an unmetered backend has no allowance to have
                    # left, and showing one invites the reader to believe it can run out.
                    "requests_remaining": (
                        self.ledger.remaining(name) if backend.metered else None
                    ),
                    "metered": backend.metered,
                }
            )
        return out

    def _run(self, kind: str, call) -> tuple[Any, str, list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        for name in self.chain:
            backend = self._backend(name)
            ok, reason = backend.available()
            if not ok:
                attempts.append({"backend": name, "outcome": "skipped", "reason": reason})
                continue
            if backend.metered and self.ledger.would_exceed(name):
                attempts.append(
                    {"backend": name, "outcome": "skipped", "reason": "daily request budget spent"}
                )
                continue
            try:
                result = call(backend)
            except QuotaExceeded as exc:
                attempts.append({"backend": name, "outcome": "quota", "reason": str(exc)})
                continue
            except (ProviderUnavailable, httpx.HTTPError, OSError) as exc:
                attempts.append(
                    {"backend": name, "outcome": "failed", "reason": f"{type(exc).__name__}: {exc}"}
                )
                continue
            self.ledger.record(name, kind=kind)
            attempts.append({"backend": name, "outcome": "answered", "reason": reason})
            self.hops.extend(attempts)
            return result, name, attempts

        self.hops.extend(attempts)
        raise ProviderUnavailable(
            "no backend in the chain could answer: "
            + "; ".join(f"{a['backend']} {a['outcome']} ({a['reason']})" for a in attempts)
        )

    def generate(
        self, prompt: str, *, system: str | None = None, max_tokens: int = 1024
    ) -> Completion:
        started = time.monotonic()
        text, backend, attempts = self._run(
            "generate", lambda b: b.generate(prompt, system=system, max_tokens=max_tokens)
        )
        degraded = backend == "fake" and len(self.chain) > 1
        return Completion(
            text=text,
            backend=backend,
            elapsed_s=round(time.monotonic() - started, 3),
            degraded=degraded,
            note=(
                "Answered by the offline fixture backend because no model provider was reachable."
                if degraded
                else None
            ),
        )

    def embed(self, texts: list[str]) -> Embedding:
        if not texts:
            return Embedding(vectors=[], backend="none", dimensions=0)
        vectors, backend, _ = self._run("embed", lambda b: b.embed(texts))
        return Embedding(
            vectors=vectors,
            backend=backend,
            dimensions=len(vectors[0]) if vectors else 0,
            degraded=backend == "fake",
        )
