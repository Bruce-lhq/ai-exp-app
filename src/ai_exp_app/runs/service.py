import time
import uuid
import base64
from fastapi import APIRouter, HTTPException
from ai_exp_app.projects.api import project_or_404, remote, schema_for
from ai_exp_app.parameters.validation import validate_parameters


def apply_started_event(store, event: dict) -> bool:
    if event.get("kind") != "started":
        return False
    run = store.get("runs", event["run_id"]) or {}
    project_id = event.get("project_id") or run.get("project_id")
    if not project_id:
        return False
    with store.lock:
        old = store.get("last_runs", project_id)
        seq = event.get("seq", 0)
        if old and old.get("started_seq", 0) >= seq:
            return False
        store.put("last_runs", project_id, {"started_seq": seq, "run_id": event["run_id"], "parameters": event.get("payload", {}).get("parameters") or run.get("parameters", {}), "code": run.get("code", {})})
    return True


class RunService:
    def __init__(self, store):
        self.store = store
        self.connection = {"connected": False, "error": "尚未连接", "last_checked": None}
        self.snapshot = {"runs": [], "queue": [], "paused": False, "revision": 0, "gpus": [], "events": []}

    def alias(self):
        projects = self.store.list("projects")
        return projects[0].get("ssh_alias", "gpu") if projects else "gpu"

    def refresh(self):
        if not self.store.list("projects") and not self.store.list("runs"):
            return
        try:
            result = remote(self.alias(), "status", {})
            self.snapshot = result
            self.connection = {"connected": True, "error": None, "last_checked": time.time()}
            runs = result.get("runs", [])
            if isinstance(runs, dict):
                runs = list(runs.values())
            for run in runs:
                id = run.get("run_id", run.get("id"))
                old = self.store.get("runs", id) or {}
                project = self.store.get("projects", run.get("project_id", old.get("project_id", ""))) or {}
                combined = {**old, **run, "id": id, "run_id": id, "ssh_alias": project.get("ssh_alias", self.alias())}
                combined["run_dir"] = run.get("run_dir") or run.get("remote_path") or old.get("run_dir")
                combined["remote_path"] = combined["run_dir"]
                self.store.put("runs", id, combined)
            # Terminal-launched experiments are visible for monitoring, but remain
            # outside the platform queue and cannot be stopped from this UI.
            external = remote(self.alias(), "external_status", {"ssh_alias": self.alias()}).get("runs", [])
            for run in external:
                if not self.store.get("runs", run["id"]):
                    self.store.put("runs", run["id"], run)
            for event in result.get("events", []):
                apply_started_event(self.store, event)
                if event.get("kind") == "failed":
                    event_id = event.get("event_id", str(event.get("seq")))
                    if not self.store.get("notifications", event_id):
                        run = self.store.get("runs", event.get("run_id", "")) or {}
                        self.store.put("notifications", event_id, {"id": event_id, "run_id": event.get("run_id"), "title": f"实验失败：{run.get('display_name', '未命名实验')}", "body": str(event.get("payload", {}).get("error", "请查看实验日志"))[:400] + "；后续队列已暂停", "read": False, "delivered": False, "created_at": time.time()})
        except Exception as exc:
            message = str(getattr(exc, "detail", exc))
            self.connection = {"connected": False, "error": message, "last_checked": time.time()}

    def run(self, id):
        run = self.store.get("runs", id)
        if not run:
            raise HTTPException(404, "实验不存在")
        return run

    def create_router(self):
        router = APIRouter(prefix="/api")

        @router.get("/connection")
        def connection():
            return self.connection

        @router.post("/connection/refresh")
        def refresh():
            self.refresh()
            return self.connection

        @router.get("/runs")
        def runs():
            return self.store.list("runs")

        @router.get("/runs/{id}")
        def run(id: str):
            return self.run(id)

        @router.post("/runs", status_code=201)
        def submit(body: dict):
            project = project_or_404(self.store, body.get("project_id", ""))
            code = body.get("code") or project.get("code", {"kind": "working_tree", "ref": None})
            schema = schema_for(self.store, project["id"], code, refresh=True)
            result = validate_parameters(schema["fields"], body.get("parameters", {}))
            if result["errors"]:
                raise HTTPException(422, result)
            id = body.get("run_id") or body.get("request_id") or str(uuid.uuid4())
            mode = body.get("mode", "start")
            if mode == "immediate":
                mode = "start"
            if mode not in {"start", "queue"}:
                raise HTTPException(422, "请选择启动或加入队列")
            config = project.get("config", {})
            payload = {"run_id": id, "project_id": project["id"], "display_name": body.get("display_name") or body.get("name") or project["name"], "parameters": result["parameters"], "code": code, "mode": mode, "project": {"path": project["remote_path"], "python": config.get("python", "/your_exp/venv/bin/python"), "runs_root": config.get("runs_root", "/your_exp/runs"), "data_root": config.get("data_root", "/your_exp/data/fineweb_edu_gpt2_100B")}}
            request_id = body.get("request_id") or id
            pending = self.store.get("submissions", request_id)
            if pending and pending["payload"] != payload:
                raise HTTPException(409, "此请求标识已用于不同参数")
            self.store.put("submissions", request_id, {"id": request_id, "payload": payload, "alias": project["ssh_alias"]})
            response = remote(project["ssh_alias"], "submit", payload, request_id=request_id)
            initial = {**payload, "id": id, "status": "queued" if mode == "queue" else "starting", "ssh_alias": project["ssh_alias"]}
            self.store.put("runs", id, initial)
            self.refresh()
            return {**(self.store.get("runs", id) or initial), "warnings": result["warnings"], "submission": response}

        @router.get("/requests/{id}")
        def request(id: str):
            pending = self.store.get("submissions", id)
            return remote(pending.get("alias", self.alias()) if pending else self.alias(), "request_status", {"request_id": id})

        @router.post("/runs/{id}/stop")
        def stop(id: str, body: dict):
            item = self.run(id)
            if body.get("confirmed") is not True:
                raise HTTPException(409, "停止实验需要确认")
            result = remote(item.get("ssh_alias", self.alias()), "stop", {"run_id": id, "confirmed": True, "pause_queue": bool(body.get("pause_queue"))}, body.get("request_id"))
            self.refresh()
            return result

        @router.post("/runs/{id}/resume")
        def resume(id: str, body: dict = {}):
            item = self.run(id)
            result = remote(item.get("ssh_alias", self.alias()), "resume", {"run_id": id, "mode": body.get("mode", "queue")}, body.get("request_id"))
            self.refresh()
            return result

        @router.get("/runs/{id}/log")
        def log(id: str, offset: int = 0, limit: int = 65536):
            item = self.run(id)
            payload = {"run_id": id, "offset": max(0, offset), "limit": min(max(limit, 1), 262144)}
            if item.get("external"):
                payload["path"] = item.get("remote_path")
            result = remote(item.get("ssh_alias", self.alias()), "read_log", payload)
            if 'text' not in result:
                result['text'] = result['content'] if 'content' in result else base64.b64decode(result.get('data', '')).decode('utf-8', errors='replace')
            return result

        @router.get("/queue")
        def queue():
            items = self.snapshot.get("queue", [])
            values = [self.store.get("runs", x) if isinstance(x, str) else x for x in items]
            return {"runs": [v for v in values if v], "paused": self.snapshot.get("paused", False), "revision": self.snapshot.get("revision", 0)}

        @router.put("/queue/order")
        def reorder(body: dict):
            result = remote(self.alias(), "queue_order", body)
            self.refresh()
            return result

        @router.post("/queue/pause")
        def pause(body: dict = {}):
            result = remote(self.alias(), "queue_pause", {})
            self.refresh()
            return result

        @router.post("/queue/resume")
        def unpause(body: dict = {}):
            result = remote(self.alias(), "queue_resume", {})
            self.refresh()
            return result

        @router.delete("/queue/{id}")
        def dequeue(id: str):
            result = remote(self.alias(), "queue_remove", {"run_id": id})
            self.refresh()
            return result

        @router.get("/gpus")
        def gpus():
            return self.snapshot.get("gpus", [])

        return router
