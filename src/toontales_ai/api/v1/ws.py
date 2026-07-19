import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from toontales_ai.domain.models import GenerationRun, Project
from toontales_ai.storage.db import AsyncSessionLocal
from toontales_ai.ws.events import redis_client
from toontales_ai.ws.tickets import consume_ticket

router = APIRouter()

# Лимит одновременных WS-соединений на процесс (review.md §10, пробел "лимит соединений").
MAX_CONNECTIONS = 1000
_active_connections = 0


@router.websocket("/ws/runs/{run_id}")
async def run_events_ws(websocket: WebSocket, run_id: str) -> None:
    global _active_connections

    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=4401)
        return

    identity = consume_ticket(ticket)
    if identity is None:
        await websocket.close(code=4401)
        return
    user_id, ticket_run_id = identity
    if str(ticket_run_id) != run_id:
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as session:
        run = (await session.execute(select(GenerationRun).where(GenerationRun.id == ticket_run_id))).scalar_one_or_none()
        if run is None:
            await websocket.close(code=4404)
            return
        project = (await session.execute(select(Project).where(Project.id == run.project_id))).scalar_one()
        if project.user_id != user_id:
            await websocket.close(code=4401)
            return

    if _active_connections >= MAX_CONNECTIONS:
        await websocket.close(code=4429)
        return

    _active_connections += 1
    await websocket.accept()

    pubsub = redis_client.pubsub()
    channel = f"toontales:run:{run_id}:events"
    pubsub.subscribe(channel)

    try:
        while True:
            message = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=5.0)
            if message is not None and message["type"] == "message":
                await websocket.send_text(message["data"])
            # Keepalive/дисконнект детектируется через приём — WS не читает входящие данные от клиента,
            # но должен обнаруживать закрытие соединения.
            try:
                await asyncio.wait_for(websocket.receive(), timeout=0.01)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.unsubscribe(channel)
        pubsub.close()
        _active_connections -= 1
