"""Kanban ルーター: 10 エンドポイント."""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lib.kanban_store import KanbanStore
from ws.manager import WebSocketManager

logger = logging.getLogger("gx10-mcp")


class MessageResponse(BaseModel):
    message: str


class TextResponse(BaseModel):
    content: str


class CardRequest(BaseModel):
    title: str
    agent: str
    desc: str = ""
    board: str = "default"
    lane: str = "standard"
    size: str = "M"
    requires: str = "{}"
    depends_on: str = "[]"


class ClaimRequest(BaseModel):
    card_id: str
    agent: str


class DoneRequest(BaseModel):
    card_id: str
    agent: str
    result: str = ""


class ReserveRequest(BaseModel):
    resource: str
    agent: str
    amount: int = 1
    name: str = ""
    reason: str = ""


class ReleaseRequest(BaseModel):
    resource: str
    agent: str
    name: str = ""


class AndonRequest(BaseModel):
    reason: str
    agent: str


class SignalRequest(BaseModel):
    event: str
    agent: str
    data: str = ""


def make_router(store: KanbanStore, ws_manager: WebSocketManager) -> APIRouter:
    """ルーターファクトリ — KanbanStore と WebSocketManager を注入."""
    router = APIRouter(prefix="/kanban")

    def require_store():
        if store._redis is None:
            raise HTTPException(
                status_code=503,
                detail="Kanban service unavailable: Redis not connected",
            )
        return store

    @router.post("/card", response_model=MessageResponse)
    async def card(req: CardRequest) -> MessageResponse:
        s = require_store()
        try:
            req_dict = json.loads(req.requires) if isinstance(req.requires, str) else req.requires
            dep_list = json.loads(req.depends_on) if isinstance(req.depends_on, str) else req.depends_on
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=422, detail=f"Invalid JSON: {e}")

        try:
            result = await s.card_create(
                req.title, req.agent,
                desc=req.desc, board=req.board, lane=req.lane, size=req.size,
                requires=req_dict, depends_on=dep_list,
            )
            msg = f"Card created: {result['card_id']} → [{result['column']}]"
            if result.get("warning"):
                msg += result["warning"]
            return MessageResponse(message=msg)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.post("/claim", response_model=MessageResponse)
    async def claim(req: ClaimRequest) -> MessageResponse:
        s = require_store()
        try:
            result = await s.card_claim(req.card_id, req.agent)
            return MessageResponse(message=f"Claimed: {req.card_id} → [{result['column']}] (owner: {req.agent})")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.post("/done", response_model=MessageResponse)
    async def done(req: DoneRequest) -> MessageResponse:
        s = require_store()
        try:
            res = await s.card_done(req.card_id, req.agent, req.result)
            cycle = f" (cycle: {res['cycle_time']})" if res.get("cycle_time") else ""
            return MessageResponse(message=f"Done: {req.card_id} → [{res['column']}]{cycle}")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.get("/board", response_model=TextResponse)
    async def board(board_name: str = "default", lane: str = "", column: str = "") -> TextResponse:
        s = require_store()
        content = await s.board_view(
            board=board_name,
            lane=lane or None,
            column=column or None,
        )
        return TextResponse(content=content)

    @router.post("/reserve", response_model=MessageResponse)
    async def reserve(req: ReserveRequest) -> MessageResponse:
        s = require_store()
        try:
            result = await s.resource_reserve(req.resource, req.agent, req.amount, req.name, req.reason)
            return MessageResponse(message=f"Reserved: {req.resource} ({result['amount']}) by {req.agent}")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.post("/release", response_model=MessageResponse)
    async def release(req: ReleaseRequest) -> MessageResponse:
        s = require_store()
        try:
            await s.resource_release(req.resource, req.agent, req.name)
            return MessageResponse(message=f"Released: {req.resource} by {req.agent}")
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.get("/resources", response_model=TextResponse)
    async def resources() -> TextResponse:
        s = require_store()
        return TextResponse(content=await s.resource_list())

    @router.post("/andon", response_model=MessageResponse)
    async def andon(req: AndonRequest) -> MessageResponse:
        s = require_store()
        result = await s.andon(req.agent, req.reason)
        blocked = result["blocked_cards"]
        msg = (
            f"ANDON triggered by {req.agent}: {req.reason}\n"
            f"Blocked cards: {blocked if blocked else '(none active)'}"
        )
        # WebSocket にブロードキャスト
        event = {"type": "andon", "agent": req.agent, "reason": req.reason}
        await ws_manager.publish(store._redis, event)
        return MessageResponse(message=msg)

    @router.post("/signal", response_model=MessageResponse)
    async def signal(req: SignalRequest) -> MessageResponse:
        s = require_store()
        result = await s.signal_emit(req.event, req.agent, req.data)
        event = {"type": "signal", "event": req.event, "agent": req.agent, "data": req.data}
        await ws_manager.publish(store._redis, event)
        return MessageResponse(message=f"Signal emitted: {req.event} ({result['event_id']})")

    @router.get("/watch", response_model=TextResponse)
    async def watch(filter: str = "*", timeout: int = 30) -> TextResponse:
        s = require_store()
        result = await s.watch(filter, timeout)
        if result.get("status") == "timeout":
            return TextResponse(content=result["message"])
        return TextResponse(content=f"Event: {result['type']} by {result['agent']}\nData: {result['data']}")

    return router
