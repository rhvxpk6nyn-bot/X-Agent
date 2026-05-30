"""FastAPI backend for the X-Agent web interface."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from core.config import config
from core.memory import COLD_DIR, HOT_DIR, WARM_DIR, Memory, store as memory_store
from core.orchestrator import Orchestrator
from core.skills import skills as skill_registry
from core.tools import tools as tool_registry
from core.platform import PLATFORM as _platform_name

app = FastAPI(title="X-Agent Web")

_sessions: dict[str, dict] = {}


def _get_or_create_session(session_id: str, model: str) -> Orchestrator:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "orch": Orchestrator(model=model),
            "model": model,
            "created": time.time(),
            "title": "New Chat",
        }
    return _sessions[session_id]["orch"]


class ChatRequest(BaseModel):
    message: str
    model: str = config.default_model
    session_id: str = "default"


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    orch = _get_or_create_session(req.session_id, req.model)
    response = orch.chat(req.message)
    return {"response": response, "stats": orch.stats()}


@app.get("/api/sessions")
async def api_sessions():
    return {
        "sessions": [
            {
                "id": sid,
                "title": s["title"],
                "model": s["model"],
                "messages": len(s["orch"].messages),
                "created": s["created"],
            }
            for sid, s in sorted(_sessions.items(), key=lambda item: item[1]["created"], reverse=True)
        ]
    }


@app.get("/api/sessions/{session_id}")
async def api_session_detail(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"id": session_id, "title": "New Chat", "model": config.default_model, "messages": []}
    orch = session["orch"]
    return {
        "id": session_id,
        "title": session["title"],
        "model": session["model"],
        "messages": orch.messages,
    }


@app.post("/api/sessions")
async def api_session_create(model: str = config.default_model):
    sid = f"session-{uuid.uuid4().hex[:12]}"
    _get_or_create_session(sid, model)
    return {"session_id": sid, "title": "New Chat"}


@app.patch("/api/sessions/{session_id}")
async def api_session_update(session_id: str, payload: dict):
    if session_id in _sessions:
        title = str(payload.get("title", "")).strip()
        if title:
            _sessions[session_id]["title"] = title[:80]
    return {"status": "ok"}


@app.delete("/api/sessions/{session_id}")
async def api_session_delete(session_id: str):
    _sessions.pop(session_id, None)
    return {"status": "ok"}


@app.get("/api/memory")
async def api_memory():
    tier_dirs = {"hot": HOT_DIR, "warm": WARM_DIR, "cold": COLD_DIR}
    tiers: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    all_memories: list[Memory] = []
    for tier, directory in tier_dirs.items():
        files = sorted(directory.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        memories = [Memory.from_file(path) for path in files[:8]]
        tiers[tier] = [memory.to_dict() for memory in memories]
        counts[tier] = len(files)
        all_memories.extend(memories)
    recent = sorted(all_memories, key=lambda memory: memory.created_at, reverse=True)[:6]
    return {
        "hot": [m.to_dict() for m in memory_store.get_hot()],
        "recent": [m.to_dict() for m in recent],
        "tiers": tiers,
        "counts": counts,
    }


@app.post("/api/memory")
async def api_memory_add(item: dict):
    mem = Memory(
        memory_id=f"web-{time.time_ns()}",
        mtype=str(item.get("type", "note")),
        title=str(item.get("title", "")),
        content=str(item.get("content", "")),
        tags=item.get("tags", []),
        importance=float(item.get("importance", 0.5)),
    )
    memory_store.add(mem, "warm")
    return {"status": "ok", "id": mem.id}


@app.get("/api/skills")
async def api_skills():
    return {
        "skills": [skill.to_dict() for skill in skill_registry.skills.values()],
        "count": len(skill_registry.skills),
        "installer": "clawhub install <slug> --dir ~/.agent/skills/installed",
        "paths": {
            "installed": str(Path.home() / ".agent" / "skills" / "installed"),
            "legacy": str(Path.home() / "agent" / "skills" / "installed"),
        },
    }


@app.get("/api/config")
async def api_config():
    return {
        "default_model": config.default_model,
        "models": list(config.models.keys()),
        "tools": list(tool_registry._tools.keys()),
        "platform": _platform_name,
    }


async def _stream_events(orch: Orchestrator, message: str):
    loop = asyncio.get_running_loop()
    sentinel = object()
    events = iter(orch.chat_stream(message))
    while True:
        event = await loop.run_in_executor(None, lambda: next(events, sentinel))
        if event is sentinel:
            break
        yield event


@app.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    session_id = "default"

    async def send(payload: dict):
        await ws.send_text(json.dumps(payload, ensure_ascii=False))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action", "chat")
            session_id = msg.get("session_id", session_id)
            model = msg.get("model", config.default_model)

            if action == "chat":
                text = str(msg.get("message", "")).strip()
                if not text:
                    continue
                orch = _get_or_create_session(session_id, model)
                async for event in _stream_events(orch, text):
                    if event.kind == "thinking":
                        await send({"type": "thinking", "content": event.data})
                    elif event.kind == "chunk":
                        await send({"type": "chunk", "content": event.data})
                    elif event.kind == "tool_call":
                        await send({"type": "tool_call", **event.data})
                    elif event.kind == "tool_result":
                        await send({"type": "tool_result", **event.data})
                    elif event.kind == "done":
                        await send({"type": "done", "stats": orch.stats()})

            elif action == "reset":
                if session_id in _sessions:
                    _sessions[session_id]["orch"].reset()
                await send({"type": "reset"})

    except WebSocketDisconnect:
        return
    except Exception as exc:
        await send({"type": "error", "content": str(exc)})


@app.get("/")
async def index():
    html = Path(__file__).parent.parent / "frontend" / "index.html"
    if html.exists():
        return HTMLResponse(html.read_text())
    return HTMLResponse("<h1>X-Agent Web</h1><p>Frontend missing.</p>")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)
