"""Hybrid retrieval: lexical and semantic, fused by rank rather than by score.

Three things are combined.

**BM25** is the lexical half. It needs no network, no key and no quota, and it is very good at the
questions this corpus actually gets — ones naming a specific community, a specific decree or a
specific fee. It is also the floor: when everything else is unavailable, retrieval still works.

**Embeddings** are the semantic half, from whichever provider the chain reaches. They catch the
questions BM25 misses, where the words differ but the meaning does not. Vectors are cached by text
hash, so re-indexing an unchanged corpus spends no quota.

**Reciprocal rank fusion** combines them. Fusing on rank rather than score matters: a BM25 score
and a cosine similarity are not on the same scale and no fixed weight between them is meaningful,
whereas "appeared third in one list and first in the other" is comparable without tuning.

When the embedding tier is unreachable, retrieval degrades to a TF-IDF/SVD approximation fitted on
the corpus itself, and the result says it degraded. Nothing silently pretends to be semantic when
it is not.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rag.indexer import EMBED_CACHE, Chunk, load_index
from rag.provider import LLMProvider, ProviderUnavailable

# The constant in reciprocal rank fusion. 60 is the value from the original paper and is not
# sensitive; it exists to stop the top rank dominating everything below it.
RRF_K = 60
TOKEN = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


@dataclass
class Hit:
    chunk: Chunk
    score: float
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    rerank_position: int | None = None
    matched_entity: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk.id,
            "text": self.chunk.text,
            "score": round(self.score, 5),
            "lexical_rank": self.lexical_rank,
            "semantic_rank": self.semantic_rank,
            "rerank_position": self.rerank_position,
            "matched_entity": self.matched_entity,
            "citation": self.chunk.citation,
        }


@dataclass
class RetrievalResult:
    hits: list[Hit]
    degraded: bool
    notes: list[str] = field(default_factory=list)
    semantic_backend: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "hits": [h.as_dict() for h in self.hits],
            "degraded": self.degraded,
            "notes": self.notes,
            "semantic_backend": self.semantic_backend,
        }


class EmbeddingCache:
    """Vectors on disk, keyed by the hash of their text.

    Quota is spent per request, so embedding the same chunk twice costs twice. Caching means
    re-indexing an unchanged corpus is free and the day's allowance goes on new material.
    """

    def __init__(self, path: Path = EMBED_CACHE) -> None:
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(text: str, backend: str) -> str:
        return hashlib.sha256(f"{backend}:{text}".encode()).hexdigest()[:24]

    def get(self, text: str, backend: str) -> list[float] | None:
        file = self.path / f"{self.key(text, backend)}.json"
        if not file.exists():
            return None
        try:
            return json.loads(file.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, text: str, backend: str, vector: list[float]) -> None:
        (self.path / f"{self.key(text, backend)}.json").write_text(json.dumps(vector))


class LexicalIndex:
    """BM25 over the corpus. The floor that always works."""

    def __init__(self, chunks: list[Chunk]) -> None:
        from rank_bm25 import BM25Okapi

        self.chunks = chunks
        self.corpus = [tokenize(c.text) for c in chunks]
        self.bm25 = BM25Okapi(self.corpus) if self.corpus else None

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        if not self.bm25:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(scores)[::-1][:k]
        return [(int(i), float(scores[i])) for i in order if scores[i] > 0]


class OfflineEmbedder:
    """TF-IDF reduced by SVD, fitted on the corpus itself.

    Weakly semantic — it captures co-occurrence rather than meaning — but it needs no network and
    no key, so it is a genuine fallback rather than a placeholder. Anything using it is reported as
    degraded, because co-occurrence is not the same as understanding.
    """

    def __init__(self, texts: list[str], *, dimensions: int = 256, seed: int = 217) -> None:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vectorizer = TfidfVectorizer(
            lowercase=True, stop_words="english", ngram_range=(1, 2), min_df=1
        )
        matrix = self.vectorizer.fit_transform(texts)
        components = max(2, min(dimensions, matrix.shape[1] - 1, max(2, matrix.shape[0] - 1)))
        self.svd = TruncatedSVD(n_components=components, random_state=seed)
        reduced = self.svd.fit_transform(matrix)
        self.vectors = self._normalise(reduced)

    @staticmethod
    def _normalise(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._normalise(self.svd.transform(self.vectorizer.transform(texts)))


class SemanticIndex:
    """Vector search over whatever embedding source is reachable."""

    def __init__(
        self,
        chunks: list[Chunk],
        provider: LLMProvider | None = None,
        cache: EmbeddingCache | None = None,
    ) -> None:
        self.chunks = chunks
        self.texts = [c.text for c in chunks]
        self.cache = cache or EmbeddingCache()
        self.backend: str | None = None
        self.degraded = False
        self.note: str | None = None
        self.matrix: np.ndarray | None = None
        self.offline: OfflineEmbedder | None = None
        self._build(provider)

    def _build(self, provider: LLMProvider | None) -> None:
        if provider is not None and self.texts:
            try:
                vectors = self._embed_with_cache(provider, self.texts)
                self.matrix = OfflineEmbedder._normalise(np.array(vectors, dtype=float))
                self.provider = provider
                return
            except ProviderUnavailable as exc:
                self.note = f"embedding provider unavailable: {exc}"

        if self.texts:
            self.offline = OfflineEmbedder(self.texts)
            self.matrix = self.offline.vectors
            self.backend = "tfidf-svd"
            self.degraded = True
            fallback = (
                "using a TF-IDF approximation fitted on the corpus, which captures co-occurrence "
                "rather than meaning"
            )
            # Both reasons, not just the first: why the provider was unusable and what replaced it.
            self.note = f"{self.note}; {fallback}" if self.note else fallback
        self.provider = provider

    def _embed_with_cache(self, provider: LLMProvider, texts: list[str]) -> list[list[float]]:
        # Probe the backend name with one text so cache keys are stable per backend.
        probe = provider.embed([texts[0]])
        self.backend = probe.backend
        self.degraded = probe.degraded
        if probe.degraded:
            raise ProviderUnavailable("only the offline fixture backend is available")

        vectors: list[list[float]] = []
        pending: list[tuple[int, str]] = []
        for i, text in enumerate(texts):
            cached = self.cache.get(text, probe.backend)
            if cached is None:
                pending.append((i, text))
                vectors.append([])
            else:
                vectors.append(cached)

        if pending:
            fresh = provider.embed([t for _, t in pending])
            for (i, text), vector in zip(pending, fresh.vectors, strict=True):
                vectors[i] = vector
                self.cache.put(text, probe.backend, vector)
        return vectors

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        if self.matrix is None or not len(self.matrix):
            return []
        if self.offline is not None:
            vector = self.offline.encode([query])[0]
        else:
            try:
                embedded = self.provider.embed([query])
                vector = np.array(embedded.vectors[0], dtype=float)
                vector /= np.linalg.norm(vector) or 1.0
            except ProviderUnavailable:
                return []
        scores = self.matrix @ vector
        order = np.argsort(scores)[::-1][:k]
        return [(int(i), float(scores[i])) for i in order]


def reciprocal_rank_fusion(
    rankings: list[list[tuple[int, float]]], *, k: int = RRF_K
) -> dict[int, float]:
    """Fuse ranked lists by position rather than by score.

    A BM25 score and a cosine similarity live on different scales, so no fixed weight between them
    means anything. Position does: appearing third in one list and first in another is comparable
    without any tuning.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for position, (index, _score) in enumerate(ranking, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + position)
    return fused


class EntityIndex:
    """Which chunk holds the facts for each place the corpus knows about.

    A question naming a specific community wants that community's numbers, and pure similarity
    does not guarantee them: "what is the net yield in JVC" is topically dominated by prose about
    how net yield is defined, which is relevant but is not the answer. Detecting the entity and
    ensuring its fact chunk is in the candidate set makes the difference between explaining the
    concept and answering the question.
    """

    def __init__(self, chunks: list[Chunk]) -> None:
        self.by_name: dict[str, int] = {}
        for i, chunk in enumerate(chunks):
            if chunk.kind != "fact":
                continue
            names = [chunk.title, chunk.meta.get("area_key", "")]
            names += list(chunk.meta.get("aliases") or [])
            for name in names:
                cleaned = str(name).strip().lower()
                if len(cleaned) >= 3:
                    self.by_name[cleaned] = i

    def detect(self, query: str) -> list[int]:
        """Fact chunks for every place the query names, longest name first.

        Longest first so "Dubai Marina" wins over "Dubai" when both are known.
        """
        low = f" {query.lower()} "
        found: list[int] = []
        for name in sorted(self.by_name, key=len, reverse=True):
            # Word-boundary match, so "dso" does not fire inside another word.
            if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", low):
                index = self.by_name[name]
                if index not in found:
                    found.append(index)
        return found


class Retriever:
    def __init__(
        self,
        chunks: list[Chunk] | None = None,
        provider: LLMProvider | None = None,
        *,
        cache: EmbeddingCache | None = None,
    ) -> None:
        self.chunks = chunks if chunks is not None else load_index()
        self.lexical = LexicalIndex(self.chunks)
        self.semantic = SemanticIndex(self.chunks, provider, cache)
        self.entities = EntityIndex(self.chunks)
        self.provider = provider

    def retrieve(self, query: str, *, k: int = 5, candidates: int = 20) -> RetrievalResult:
        if not self.chunks:
            return RetrievalResult(hits=[], degraded=True, notes=["the index is empty"])

        lexical = self.lexical.search(query, candidates)
        semantic = self.semantic.search(query, candidates)

        lexical_rank = {i: r for r, (i, _) in enumerate(lexical, start=1)}
        semantic_rank = {i: r for r, (i, _) in enumerate(semantic, start=1)}

        # A named place contributes its own ranked list, so its facts are always a candidate for a
        # question that names it.
        entities = self.entities.detect(query)
        entity_ranking = [(i, 1.0) for i in entities]
        fused = reciprocal_rank_fusion(
            [lexical, semantic, entity_ranking] if entity_ranking else [lexical, semantic]
        )

        notes: list[str] = []
        if entities:
            named = ", ".join(self.chunks[i].title for i in entities)
            notes.append(
                f"the question names {named}, so that area's recorded figures were included"
            )
        if self.semantic.note:
            notes.append(self.semantic.note)
        if not semantic:
            notes.append("semantic search returned nothing; the answer rests on lexical matching")

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        hits = [
            Hit(
                chunk=self.chunks[i],
                score=score,
                lexical_rank=lexical_rank.get(i),
                semantic_rank=semantic_rank.get(i),
                matched_entity=i in entities,
            )
            for i, score in ordered
        ]
        return RetrievalResult(
            hits=hits,
            degraded=self.semantic.degraded,
            notes=notes,
            semantic_backend=self.semantic.backend,
        )
