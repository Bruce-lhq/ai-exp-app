import json
import re
import uuid
from pathlib import PurePosixPath
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from ai_exp_app.parameters.validation import validate_parameters


def remote(alias, operation, payload, request_id=None):
    from ai_exp_app.transport.ssh import call_remote
    try:
        return call_remote(alias, {"version": 1, "request_id": request_id or str(uuid.uuid4()), "operation": operation, "payload": payload}, timeout_s=40)
    except Exception as exc:
        detail = str(exc)
        if getattr(exc, 'details', None):
            detail += '\n' + str(exc.details)
        status = 409 if getattr(exc, 'code', '') in {'REVISION_CONFLICT','QUEUE_AHEAD','QUEUE_PAUSED','RESOURCE_UNAVAILABLE','REQUEST_CONFLICT','QUEUE_STATE'} else 502
        raise HTTPException(status, detail) from exc


def project_or_404(store, id):
    item = store.get("projects", id)
    if not item:
        raise HTTPException(404, "项目不存在")
    return item


def schema_for(store, id, code=None, refresh=False):
    project = project_or_404(store, id)
    code = code or project.get("code", {"kind": "working_tree", "ref": None})
    cached = store.get("schemas", id)
    if not refresh and cached and cached.get("code") == code:
        return cached
    result = remote(project["ssh_alias"], "read_schema", {"path": project["remote_path"], "code": code, "python": project.get("config", {}).get("python", "/your_exp/venv/bin/python")})
    fields = result.get("fields", result.get("schema", []))
    if not isinstance(fields, list):
        raise HTTPException(502, "远端没有返回可用参数定义")
    result = {**result, "fields": fields, "code": code}
    store.put("schemas", id, result)
    project["code"] = code
    store.put("projects", id, project)
    if not any(p["project_id"] == id for p in store.list("presets")) and not project.get("initialized"):
        defaults = validate_parameters(fields, {"training": {}, "runtime": {"gpu_count": 8}})["parameters"]
        preset_id = str(uuid.uuid4())
        store.put("presets", preset_id, {"id": preset_id, "project_id": id, "name": "源码默认值", "parameters": defaults})
        project["initialized"] = True
        store.put("projects", id, project)
    return result


def create_router(store):
    router = APIRouter(prefix="/api")

    @router.get("/projects")
    def projects():
        return [p for p in store.list("projects") if p.get("favorite", True)]

    @router.post("/projects", status_code=201)
    def create_project(body: dict):
        name = str(body.get("name", "")).strip()
        path = str(body.get("remote_path", body.get("path", "")))
        alias = str(body.get("ssh_alias", body.get("host", "gpu")))
        if not name or not path.startswith("/") or "\0" in path or not re.fullmatch(r"[A-Za-z0-9_.-]+", alias) or alias.startswith("-"):
            raise HTTPException(422, "填写项目名称、SSH 别名和远端绝对目录")
        existing = next((p for p in store.list("projects") if p["ssh_alias"] == alias and p["remote_path"] == path), None)
        id = existing["id"] if existing else str(uuid.uuid4())
        return store.put("projects", id, {**(existing or {}), "id": id, "name": name, "ssh_alias": alias, "remote_path": path, "favorite": True, "config": body.get("config", existing.get("config", {}) if existing else {})})

    @router.patch("/projects/{id}")
    def update_project(id: str, body: dict):
        item = project_or_404(store, id)
        for key in ("name", "config", "code"):
            if key in body:
                item[key] = body[key]
        if not str(item["name"]).strip():
            raise HTTPException(422, "项目名不能为空")
        return store.put("projects", id, item)

    @router.delete("/projects/{id}")
    def remove_project(id: str):
        item = project_or_404(store, id)
        item["favorite"] = False
        return store.put("projects", id, item)

    @router.post("/remote/browse")
    def browse(body: dict):
        return remote(body.get("ssh_alias", "gpu"), "list_directory", {"path": body.get("path", "/your_exp/projects")})

    @router.post("/projects/{id}/inspect")
    def inspect(id: str):
        p = project_or_404(store, id)
        return remote(p["ssh_alias"], "inspect_project", {"path": p["remote_path"]})

    @router.post("/projects/{id}/schema")
    def schema(id: str, body: dict = {}):
        return schema_for(store, id, body.get("code"), refresh=True)

    @router.get("/projects/{id}/presets")
    def presets(id: str):
        return [p for p in store.list("presets") if p["project_id"] == id]

    def save_preset(id, body, preset_id=None):
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(422, "参数组名称不能为空")
        parameters = body.get("parameters", {})
        if "parameters" in parameters:
            parameters = parameters["parameters"]
        result = validate_parameters(schema_for(store, id)["fields"], parameters)
        if result["errors"]:
            raise HTTPException(422, result)
        with store.lock:
            same = next((p for p in store.list("presets") if p["project_id"] == id and p["name"] == name and p["id"] != preset_id), None)
            if same:
                raise HTTPException(409, "已有同名参数组，请改名或明确保存到该组")
            actual_id = preset_id or str(uuid.uuid4())
            p = store.put("presets", actual_id, {"id": actual_id, "project_id": id, "name": name, "parameters": result["parameters"]})
        return {**p, "warnings": result["warnings"]}

    @router.post("/projects/{id}/presets", status_code=201)
    def new_preset(id: str, body: dict):
        return save_preset(id, body)

    @router.post("/projects/{id}/presets/import", status_code=201)
    def import_preset(id: str, body: dict):
        doc = body.get("document", body.get("parameters", {}))
        if not isinstance(doc, dict):
            raise HTTPException(422, "JSON 内容必须为对象")
        return save_preset(id, {"name": body.get("name") or doc.get("name") or "导入参数组", "parameters": doc.get("parameters", doc)})

    def owned_preset(id, pid):
        preset = store.get("presets", pid)
        if not preset or preset["project_id"] != id:
            raise HTTPException(404, "参数组不存在")
        return preset

    @router.put("/projects/{id}/presets/{pid}")
    def update_preset(id: str, pid: str, body: dict):
        preset = owned_preset(id, pid)
        return save_preset(id, {**preset, **body}, pid)

    @router.delete("/projects/{id}/presets/{pid}")
    def delete_preset(id: str, pid: str):
        owned_preset(id, pid)
        store.delete("presets", pid)
        return {"ok": True}

    @router.get("/projects/{id}/presets/{pid}/export")
    def export_preset(id: str, pid: str, format: str = "json"):
        p = owned_preset(id, pid)
        if format == "json":
            return {"version": 1, "name": p["name"], "parameters": p["parameters"]}
        fields = {f["key"]: f for f in schema_for(store, id)["fields"]}
        def escape(v):
            return str(v).replace("|", "\\|").replace("\n", "<br>")
        lines = [f"# {escape(p['name'])}", "", "| 类型 | 参数名称 | 默认值 |", "| --- | --- | --- |"]
        for key, value in p["parameters"]["training"].items():
            lines.append(f"| {escape(fields.get(key, {}).get('kind', ''))} | {escape(key)} | {escape(value)} |")
        lines.append(f"| integer | GPU 卡数 | {p['parameters']['runtime']['gpu_count']} |")
        return Response("\n".join(lines) + "\n", media_type="text/markdown")

    @router.post("/projects/{id}/parameters/validate")
    def validate(id: str, body: dict):
        return validate_parameters(schema_for(store, id)["fields"], body.get("parameters", body))

    @router.get("/projects/{id}/editor-initial")
    def initial(id: str):
        schema = schema_for(store, id)
        last = store.get("last_runs", id)
        result = validate_parameters(schema["fields"], last["parameters"] if last else {"training": {}, "runtime": {"gpu_count": 8}})
        return {**result["parameters"], "source": "last_run" if last else "defaults", "warnings": result["warnings"] if last else [], "errors": result["errors"]}

    @router.get("/projects/{id}/parameter-display")
    def get_display(id: str):
        return store.get("preferences", f"parameters:{id}") or {}

    @router.patch("/projects/{id}/parameter-display")
    @router.put("/projects/{id}/parameter-display")
    def set_display(id: str, body: dict):
        return store.put("preferences", f"parameters:{id}", body)

    return router
