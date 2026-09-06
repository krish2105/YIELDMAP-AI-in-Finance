"""The Ask endpoint, and what the system knows about its own retrieval."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from rag.ask import ask as run_ask
from rag.indexer import build_index, load_index
from rag.provider import LLMProvider
from rag.quota import QuotaLedger
from rag.retriever import Retriever

router = APIRouter(tags=["ask"])

_state: dict[str, Any] = {}


def _retriever() -> Retriever:
    """One retriever per process.

    Building it fits a TF-IDF model and may embed the whole corpus, so it is built once and reused
    rather than per request.
    """
    if "retriever" not in _state:
        provider = LLMProvider.from_env()
        chunks = load_index() or None
        if chunks is None:
            build_index()
            chunks = load_index()
        _state["provider"] = provider
        _state["retriever"] = Retriever(chunks, provider=provider)
    return _state["retriever"]


class AskRequest(BaseModel):
    question: Annotated[str, Field(min_length=3, max_length=1000)]
    k: Annotated[int, Field(ge=1, le=12)] = 5


@router.post("/ask")
def ask_endpoint(req: AskRequest) -> dict[str, Any]:
    """Answer a question from the corpus, with a citation on every factual sentence."""
    retriever = _retriever()
    answer = run_ask(req.question, retriever=retriever, provider=_state.get("provider"), k=req.k)
    return answer.as_dict()


@router.get("/ask/sources")
def sources() -> dict[str, Any]:
    """What is in the index, so a reader can see the whole evidence base."""
    chunks = load_index()
    by_kind: dict[str, int] = {}
    documents: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        by_kind[chunk.kind] = by_kind.get(chunk.kind, 0) + 1
        if chunk.kind == "doc":
            documents.setdefault(
                chunk.doc_id or chunk.title,
                {
                    "title": chunk.title,
                    "source": chunk.source,
                    "source_url": chunk.source_url,
                    "status": chunk.status,
                    "chunks": 0,
                },
            )
            documents[chunk.doc_id or chunk.title]["chunks"] += 1
    return {
        "n_chunks": len(chunks),
        "by_kind": by_kind,
        "documents": list(documents.values()),
        "unverified_documents": [
            d["title"] for d in documents.values() if d["status"] != "verified"
        ],
    }


@router.get("/ask/providers")
def providers() -> dict[str, Any]:
    """Which model backends could answer right now, and what has been spent."""
    provider = _state.get("provider") or LLMProvider.from_env()
    ledger = QuotaLedger()
    return {
        "chain": list(provider.chain),
        "backends": provider.describe(),
        "usage": ledger.report(),
    }
