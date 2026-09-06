"""Memo generation, retrieval, export, and the live view of a run.

`POST /memos` is the only write in the API, and what it writes is a document. The run streams over
server-sent events so the interface can show the crew working rather than a spinner, which matters
because a bounded agent run is the thing this project is demonstrating.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.budget import Budget
from agents.export import to_docx, to_html, to_markdown
from agents.runtime import run_crew
from agents.store import MemoStore, StoredMemo, new_id
from api.deps import WarehouseDep, db_path, require

router = APIRouter(tags=["memos"])

_store = MemoStore()


class MemoRequest(BaseModel):
    area_key: Annotated[str, Field(min_length=2, max_length=120)]
    max_requests: Annotated[int, Field(ge=1, le=200)] = 40
    max_seconds: Annotated[float, Field(ge=5, le=600)] = 180
    max_steps: Annotated[int, Field(ge=1, le=100)] = 24


def _run_and_store(req: MemoRequest) -> StoredMemo:
    result = run_crew(
        req.area_key,
        db_path=db_path(),
        budget=Budget(
            max_requests=req.max_requests,
            max_seconds=req.max_seconds,
            max_steps=req.max_steps,
        ),
    )
    memo = StoredMemo(
        id=new_id(),
        run_id=result.run_id,
        area_key=req.area_key,
        memo_md=result.memo,
        citations=result.citations,
        disagreements=result.disagreements,
        findings=[f.as_dict() for f in result.findings],
        audit=result.audit.as_dict(),
        budget=result.budget,
        status=result.status,
        provenance=result.provenance,
    )
    return _store.save(memo)


@router.post("/memos", dependencies=[require("analyst")])
def create_memo(req: MemoRequest, wh: WarehouseDep) -> dict[str, Any]:
    """Run the crew over an area and store the memo it produces.

    Restricted to the analyst role: it is the only endpoint that writes, and it is the only one
    that spends a model budget.
    """
    memo = _run_and_store(req)
    if memo.citation_coverage < 1.0:
        # The guarantee is that every stated figure is cited. A memo that fails it is not shown.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"the memo cited {memo.citation_coverage:.0%} of its figures and was rejected; "
                "every stated figure must carry a source"
            ),
        )
    return memo.as_dict()


@router.get("/memos")
def list_memos(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
    """Every memo produced, newest first."""
    memos = _store.list(limit=limit)
    return {
        "memos": [m.summary() for m in memos],
        "count": len(memos),
    }


@router.get("/memos/{memo_id}")
def get_memo(memo_id: str) -> dict[str, Any]:
    memo = _store.get(memo_id)
    if memo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such memo")
    return memo.as_dict()


@router.get("/memos/{memo_id}/export")
def export_memo(
    memo_id: str,
    fmt: Annotated[str, Query(pattern="^(md|html|docx)$")] = "md",
) -> Response:
    """Export a memo, with its citations and caveats travelling with it."""
    memo = _store.get(memo_id)
    if memo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such memo")
    body = memo.as_dict()

    if fmt == "md":
        return Response(
            content=to_markdown(body),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="memo-{memo_id}.md"'},
        )
    if fmt == "html":
        return Response(
            content=to_html(body),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="memo-{memo_id}.html"'},
        )
    return Response(
        content=to_docx(body),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="memo-{memo_id}.docx"'},
    )


def _events(req: MemoRequest):
    """The run, as a sequence of server-sent events.

    The crew is synchronous, so the stream reports each stage as it completes rather than token by
    token. That is honest about what is happening: these are discrete agents finishing discrete
    jobs, not a model streaming prose.
    """

    def event(kind: str, payload: dict[str, Any]) -> str:
        return f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"

    yield event("start", {"area_key": req.area_key, "budget": {"steps": req.max_steps}})
    try:
        memo = _run_and_store(req)
    except Exception as exc:  # noqa: BLE001 - the stream must report a failure, not drop
        yield event("error", {"detail": f"{type(exc).__name__}: {exc}"})
        return

    for finding in memo.findings:
        yield event("finding", finding)
    for item in memo.disagreements:
        yield event("disagreement", item)
    for entry in memo.audit.get("findings", []):
        yield event("audit", entry)
    yield event(
        "done",
        {
            "memo_id": memo.id,
            "run_id": memo.run_id,
            "status": memo.status,
            "citation_coverage": memo.citation_coverage,
            "blocked": memo.audit.get("blocked", False),
        },
    )


@router.post("/runs/stream", dependencies=[require("analyst")])
async def stream_run(req: MemoRequest) -> StreamingResponse:
    """Run the crew and stream its progress."""

    async def pump():
        for chunk in _events(req):
            yield chunk
            # Yield control so a slow client cannot block the event loop.
            await asyncio.sleep(0)

    return StreamingResponse(
        pump(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
