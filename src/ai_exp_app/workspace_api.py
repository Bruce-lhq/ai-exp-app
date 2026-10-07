"""Cross-device metadata exchange through the user's existing SSH connection."""
import asyncio
import json
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .history.paths import export_basename
from .transport.ssh import build_agent_argv
from .workspace_sync import SyncEngine

# Constant remote code: user data travels on stdin, never as executable text.
_FORWARD = '''import sys,json,http.cookiejar,urllib.request
value=json.load(sys.stdin)
base="http://127.0.0.1:"+str(value["port"])
client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
client.open(base+"/",timeout=10).close()
request=urllib.request.Request(base+"/api/workspace-sync/exchange",data=json.dumps(value["request"]).encode(),headers={"Content-Type":"application/json","Origin":base})
with client.open(request,timeout=20) as result: sys.stdout.write(result.read().decode())
'''


class WorkspaceSync:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.lock = threading.Lock()
        self.error = ''
        self.state = 'idle'
        self.engine = SyncEngine(store, history_factory=self.history_factory,
                                 project_factory=self.project_factory)

    def history_factory(self, record):
        source = {**record.get('source', {}), 'kind': 'remote',
                  'ssh_alias': self.config.local_settings['ssh_alias']}
        identity = record['id']
        self.config.cache_root.mkdir(parents=True, exist_ok=True)
        directory = export_basename(record.get('name', identity), identity,
                                    {p.name for p in self.config.cache_root.iterdir()})
        (self.config.cache_root / directory).mkdir()
        return {**record, 'source': source, 'source_key': json.dumps(source, sort_keys=True),
                'cache_dir': str(self.config.cache_root / directory),
                'status': 'imported', 'sync_status': 'pending',
                'created_at': datetime.now(timezone.utc).isoformat()}

    def project_factory(self, record):
        return {**record, 'ssh_alias': self.config.local_settings['ssh_alias'], 'config': {}}

    def status(self):
        result = self.engine.status()
        mode = self.config.local_settings['workspace_sync_mode']
        return {**result, 'mode': mode, 'port': int(self.config.local_settings['workspace_sync_port']),
                'state': 'conflict' if result.get('conflicts') else self.state,
                'error': self.error}

    def backup(self):
        target = self.config.data_dir / 'backups' / ('workspace-sync-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        target.mkdir(parents=True)
        with self.store.connection() as original, sqlite3.connect(target / 'app.sqlite3') as copied:
            original.backup(copied)
        if self.config.config_file.exists():
            destination = target / 'config.local.json'
            destination.write_bytes(self.config.config_file.read_bytes())
            destination.chmod(0o600)

    def forward(self, request):
        settings = self.config.local_settings
        response = subprocess.run(build_agent_argv(settings['ssh_alias'], settings, ['-c', _FORWARD]),
                                  input=json.dumps({'port': int(settings['workspace_sync_port']), 'request': request}),
                                  text=True, encoding='utf-8', capture_output=True, timeout=40)
        if response.returncode:
            raise RuntimeError('无法连接云端同步中心；本地修改会保留，恢复连接后重试')
        return json.loads(response.stdout)

    def refresh(self):
        if not self.lock.acquire(blocking=False):
            return self.status()
        try:
            mode = self.config.local_settings['workspace_sync_mode']
            if mode == 'off':
                return self.status()
            self.state, self.error = 'syncing', ''
            if mode == 'hub':
                self.engine.exchange({'changes': []})
            else:
                self.engine.reconcile(self.forward)
            self.state = 'idle'
        except Exception as exc:
            self.state, self.error = 'offline', str(exc)
        finally:
            self.lock.release()
        return self.status()

    async def worker(self):
        while True:
            await asyncio.to_thread(self.refresh)
            await asyncio.sleep(10)

    def router(self):
        router = APIRouter(prefix='/api/workspace-sync')

        @router.get('')
        def status():
            return self.status()

        @router.put('/settings')
        def settings(body: dict):
            mode = body.get('mode', 'off')
            port = str(body.get('port', 8765))
            if mode != self.config.local_settings['workspace_sync_mode'] and mode != 'off':
                self.backup()
            try:
                self.config.save_local_settings({'workspace_sync_mode': mode, 'workspace_sync_port': port})
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            self.state, self.error = 'idle', ''
            return self.status()

        @router.post('/refresh')
        def refresh():
            return self.refresh()

        @router.post('/exchange')
        def exchange(body: dict):
            if self.config.local_settings['workspace_sync_mode'] != 'hub':
                raise HTTPException(409, '请先在 GPU 后台启用云端同步中心')
            if not isinstance(body.get('changes', []), list):
                raise HTTPException(422, '无效的同步请求')
            try:
                return self.engine.exchange(body)
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(422, '无效的同步文档') from exc

        @router.post('/conflicts/{id}')
        def resolve(id: str, body: dict):
            choice = body.get('choice')
            if choice not in {'local', 'remote'}:
                raise HTTPException(422, '请选择本机或云端版本')
            try:
                with self.lock:
                    self.engine.resolve(id, choice)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            return self.refresh()

        @router.get('/view')
        def view():
            return self.store.get('preferences', 'shared_view:analysis') or {}

        @router.put('/view')
        def save_view(body: dict):
            if set(body) - {'settings', 'appearance'} or any(not isinstance(v, dict) for v in body.values()):
                raise HTTPException(422, '无效的图表设置')
            return self.store.put('preferences', 'shared_view:analysis', body)

        return router
