import asyncio
import contextlib
import os
import secrets
import uuid
import time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from ai_exp_app.config import Config
from ai_exp_app.db import Store
from ai_exp_app.security import LocalSessionMiddleware
from ai_exp_app.projects.api import create_router as project_router
from ai_exp_app.runs.service import RunService
from ai_exp_app.history.api import create_router as history_router
from ai_exp_app.history.worker import sync_once


def create_app(data_dir: Path | None = None) -> FastAPI:
    config = Config.load(data_dir)
    store = Store(config.data_dir / "app.sqlite3")
    runs = RunService(store)
    token_file = config.data_dir / "desktop-token"
    if not token_file.exists():
        fd = os.open(token_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(32))
    native_token = token_file.read_text().strip()

    async def worker():
        while True:
            await asyncio.to_thread(runs.refresh)
            await asyncio.sleep(3)

    async def history_worker():
        while True:
            await asyncio.sleep(15)
            try:
                await asyncio.to_thread(sync_once, store, config.cache_root)
            except Exception as exc:
                store.put("system", "sync_error", {"error": str(exc)})

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(worker())
        history_task = asyncio.create_task(history_worker())
        yield
        task.cancel()
        history_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(asyncio.CancelledError):
            await history_task

    app = FastAPI(title="AI 实验工作台", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.config, app.state.runs = store, config, runs
    app.state.instance_id = str(uuid.uuid4())
    app.state.desktop_seen = 0.0
    picker_requests = {}
    app.add_middleware(LocalSessionMiddleware, token=secrets.token_urlsafe(32), native_token=native_token)
    app.include_router(project_router(store))
    app.include_router(runs.create_router())
    app.include_router(history_router(store, config.cache_root))

    @app.get("/api/health")
    def health():
        return {"app": "ai-exp-app", "version": "0.1.0", "instance_id": app.state.instance_id}

    @app.post("/api/local/browse")
    def local_browse(body: dict):
        path = Path(body.get("path") or Path.home()).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(404, "目录不存在")
        try:
            entries = [{"name": child.name, "path": str(child), "is_dir": True} for child in sorted(path.iterdir()) if child.is_dir() and not child.name.startswith(".")]
        except PermissionError as exc:
            raise HTTPException(403, "无权访问此目录") from exc
        return {"path": str(path), "parent": str(path.parent), "entries": entries}

    @app.get("/api/notifications")
    def notifications():
        return store.list("notifications")

    @app.post("/api/notifications/{id}/read")
    def read_notification(id: str, body: dict = {}):
        notice = store.get("notifications", id)
        if not notice:
            raise HTTPException(404, "提醒不存在")
        notice["read"] = True
        return store.put("notifications", id, notice)

    def native_only(request):
        if not secrets.compare_digest(request.headers.get("X-Desktop-Token", ""), native_token):
            raise HTTPException(403, "仅供本机应用使用")

    @app.get("/api/native-picker/availability")
    def picker_available():
        return {"available": time.time() - app.state.desktop_seen < 25}

    @app.post("/api/native-picker")
    def picker_create(body: dict):
        if not picker_available()["available"]:
            raise HTTPException(409, "请先打开 Mac 实验工作台应用")
        with store.lock:
            now = time.time()
            for old in picker_requests.values():
                if now - old["created_at"] > 120 and old["status"] in {"pending", "presenting"}:
                    old["status"] = "cancelled"
            if any(item["status"] in {"pending", "presenting"} for item in picker_requests.values()):
                raise HTTPException(409, "已有目录选择窗口，请先完成或取消")
            id = str(uuid.uuid4())
            picker_requests[id] = {"id": id, "status": "pending", "created_at": now}
            return picker_requests[id].copy()

    @app.get("/api/native-picker/{id}")
    def picker_status(id: str):
        with store.lock:
            item = picker_requests.get(id)
            if not item:
                raise HTTPException(404, "目录选择请求不存在")
            if time.time() - item["created_at"] > 120:
                item["status"] = "cancelled"
            return {**item, "status": "pending" if item["status"] == "presenting" else item["status"]}

    @app.get("/api/desktop/picker")
    def desktop_picker(request: Request):
        native_only(request)
        with store.lock:
            for item in picker_requests.values():
                if item["status"] == "pending" and time.time() - item["created_at"] < 120:
                    item["status"] = "presenting"
                    return item.copy()
        return None

    @app.post("/api/desktop/picker/{id}")
    def picker_complete(id: str, body: dict, request: Request):
        native_only(request)
        with store.lock:
            item = picker_requests.get(id)
            if not item or item["status"] != "presenting":
                raise HTTPException(409, "目录选择请求已结束")
            path = body.get("path")
            if path and not Path(path).is_dir():
                raise HTTPException(422, "请选择存在的目录")
            item.update(status="selected" if path else "cancelled", path=path)
        return {"ok": True}

    @app.get("/api/desktop/notifications")
    def native_notifications(request: Request):
        native_only(request)
        app.state.desktop_seen = time.time()
        return [item for item in store.list("notifications") if not item.get("delivered")]

    @app.post("/api/desktop/notifications/{id}/delivered")
    def delivered(id: str, request: Request):
        native_only(request)
        notice = store.get("notifications", id)
        if notice:
            notice["delivered"] = True
            store.put("notifications", id, notice)
        return {"ok": True}

    @app.post("/api/desktop/shutdown")
    def shutdown(request: Request):
        native_only(request)
        callback = getattr(app.state, "shutdown", None)
        if callback:
            callback()
        return {"ok": callback is not None}

    if (config.web_root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=config.web_root / "assets"), name="assets")

    @app.get("/{path:path}")
    def index(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        file = (config.web_root / path).resolve()
        if file.is_relative_to(config.web_root.resolve()) and file.is_file():
            return FileResponse(file)
        index_file = config.web_root / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse('<!doctype html><html lang="zh"><meta charset="utf-8"><title>AI 实验工作台</title><body><h1>AI 实验工作台</h1><p>本地服务已就绪，网页正在构建。</p></body></html>')

    return app
