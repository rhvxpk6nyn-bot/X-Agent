"""FastAPI backend for agent Web UI."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from core.orchestrator import Orchestrator
from core.memory import store as memory_store
from core.skills import skills as skill_registry
from core.config import config

app = FastAPI(title="Agent Web UI")

# Global orchestrator instances per session
_orchestrators: dict[str, Orchestrator] = {}

# ── REST API ─────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: str = "deepseek"
    session_id: str = "default"

class MemoryItem(BaseModel):
    id: str
    title: str
    content: str
    type: str = "preference"

class SkillAction(BaseModel):
    name: str

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    orch = _orchestrators.get(req.session_id)
    if not orch:
        orch = Orchestrator(model=req.model)
        _orchestrators[req.session_id] = orch
    response = orch.chat(req.message)
    return {
        "response": response,
        "stats": orch.stats(),
    }

@app.get("/api/memory")
async def api_memory():
    hot = [m.to_dict() for m in memory_store.get_hot()]
    return {"hot": hot}

@app.post("/api/memory")
async def api_memory_add(item: MemoryItem):
    from core.memory import Memory
    mem = Memory(
        memory_id=f"web-{int(time.time())}",
        mtype=item.type,
        title=item.title,
        content=item.content,
    )
    memory_store.add(mem, "warm")
    return {"status": "ok", "id": mem.id}

@app.get("/api/skills")
async def api_skills():
    return {"skills": [s.to_dict() for s in skill_registry.skills.values()]}

@app.post("/api/skills/install")
async def api_skills_install(action: SkillAction):
    ok = skill_registry.install(action.name)
    return {"status": "ok" if ok else "failed"}

@app.get("/api/config")
async def api_config():
    return {
        "models": list(config.models.keys()),
        "default_model": config.default_model,
        "web_port": config.web_port,
    }


# ── WebSocket for streaming ──────────────────────────

@app.websocket("/ws")
async def websocket_chat(ws: WebSocket):
    await ws.accept()
    orch = Orchestrator()
    while True:
        try:
            data = await ws.receive_text()
            msg = json.loads(data)
            user_input = msg.get("message", "")

            # Stream response
            for chunk in orch.chat(user_input, stream=True):
                await ws.send_text(json.dumps({"type": "chunk", "content": chunk}))

            await ws.send_text(json.dumps({"type": "done", "stats": orch.stats()}))
        except WebSocketDisconnect:
            break
        except Exception as e:
            await ws.send_text(json.dumps({"type": "error", "content": str(e)}))


# ── Serve frontend ──────────────────────────────────

frontend_dir = Path(__file__).parent.parent / "frontend"

@app.get("/")
async def index():
    index_html = frontend_dir / "index.html"
    if index_html.exists():
        return HTMLResponse(index_html.read_text())
    return HTMLResponse("<h1>Agent Web UI</h1><p>Frontend not built. Run: cd web/frontend && npm run build</p>")

# Serve static files if built
static_dir = frontend_dir / "dist"
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")
