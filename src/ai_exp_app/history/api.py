import io
import json
import secrets
import shutil
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from .importer import enrich, import_history
from .paths import export_basename
from .sync import ALLOWED_FILES, run_lock, rpc, sync_history


def create_router(store, cache_root: Path):
    router = APIRouter()
    cache_root = Path(cache_root).resolve()

    def get(identity):
        record = store.get('history', identity)
        if not record:
            raise HTTPException(404, '历史实验不存在')
        return record

    @router.get('/api/history')
    def listing():
        return [enrich(r) for r in store.list('history') if r.get('visibility') not in {'removed', 'tracking'}]

    @router.post('/api/history/import')
    @router.post('/api/history')
    def importing(body: dict):
        source = body.get('source')
        if not isinstance(source, dict):
            source = {'kind': source or 'local', 'path': body.get('path', ''), 'ssh_alias': body.get('alias', 'gpu')}
        try:
            return import_history(store, source, cache_root, body.get('name'))
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/api/history/sync-running')
    def sync_running():
        imported = []
        for run in store.list('runs'):
            if run.get('status') not in {'running', 'stopping', 'external_running'} or not run.get('remote_path'):
                continue
            try:
                record = import_history(store, {
                    'kind': 'remote', 'path': run['remote_path'],
                    'ssh_alias': run.get('ssh_alias', 'gpu')}, cache_root,
                    run.get('display_name'), run_id=run['id'], synchronize=True,
                    visibility='visible')
                with run_lock(record['id']):
                    record = get(record['id'])
                    record.update(status=run['status'], attempts=run.get('attempts', []),
                                  stop_tokens=run.get('stop_tokens'), sync_failures=0, next_retry_at=0)
                    imported.append(store.put('history', record['id'], enrich(record)))
            except (ValueError, OSError, RuntimeError) as exc:
                imported.append({'id': run['id'], 'name': run.get('display_name'),
                                 'sync_status': 'pending', 'sync_error': str(exc)})
        return {'count': len(imported), 'items': imported}

    @router.post('/api/history/{identity}/resume-editor')
    def resume_editor(identity: str):
        from ai_exp_app.projects.api import project_payload, remote
        record = get(identity)
        source = record['source']
        if source['kind'] != 'remote' or record.get('remote_deleted'):
            raise HTTPException(422, '请导入仍保留 checkpoint 的云端实验目录')
        run = next((r for r in store.list('runs') if r.get('remote_path') == source['path']), {})
        candidates = [p for p in store.list('projects') if p.get('ssh_alias', 'gpu') == source.get('ssh_alias', 'gpu')]
        project = next((p for p in candidates if p['id'] == run.get('project_id')), None)
        if project is None:
            default = (store.get('preferences', 'workspace') or {}).get('default_project_id')
            project = next((p for p in candidates if p['id'] == default or p.get('is_default')), candidates[0] if candidates else None)
        if not project:
            raise HTTPException(422, '请先添加此云端实验使用的代码项目')
        execution = project_payload(store, project)
        value = remote(source.get('ssh_alias', 'gpu'), 'checkpoint_preview', {
            'path': source['path'], 'python': execution['python'],
            'project': {**execution, 'code': project.get('code', {'kind': 'working_tree', 'ref': None})}})
        ticket = secrets.token_urlsafe(24)
        store.put('resume_drafts', ticket, {'id': ticket, 'history_id': identity,
            'ssh_alias': source.get('ssh_alias', 'gpu'), 'path': value['path'], 'identity': value['identity']})
        return {'training': value['training'], 'runtime': value['runtime'], 'project_id': project['id'],
                'resume': {'ticket': ticket, 'path': value['path'], 'tokens_seen': value.get('tokens_seen'), 'step': value.get('step')},
                'display_name': record['name'] + ' · 续跑'}

    @router.post('/api/history/refresh')
    def refresh_history():
        warnings = []
        for candidate in store.list('history'):
            if candidate.get('visibility') in {'removed', 'tracking'} or candidate.get('remote_deleted'):
                continue
            with run_lock(candidate['id']):
                record = get(candidate['id'])
                try:
                    record.update(sync_history(record, cache_root))
                    store.put('history', record['id'], record)
                except (OSError, ValueError, RuntimeError) as exc:
                    warnings.append(f"{record['name']}：{exc}")
        return {'warnings': warnings}

    @router.patch('/api/history/{identity}')
    def update(identity: str, body: dict):
        with run_lock(identity):
            record = get(identity)
            if 'name' in body or 'display_name' in body:
                name = body.get('name', body.get('display_name'))
                old = Path(record['cache_dir'])
                if not old.resolve().is_relative_to(cache_root):
                    raise HTTPException(409, '缓存路径异常')
                try:
                    occupied = {p.name for p in cache_root.iterdir() if p != old}
                    new = cache_root / export_basename(name, identity, occupied)
                    if old.exists() and old != new:
                        old.rename(new)
                except (ValueError, OSError) as exc:
                    raise HTTPException(422, str(exc)) from exc
                record.update(name=name, display_name=name, cache_dir=str(new))
            for field in ('notes', 'tags'):
                if field in body:
                    record[field] = str(body[field]).strip() if field == 'notes' else body[field]
            visibility = body.get('visibility')
            if 'archived' in body:
                visibility = 'archived' if body['archived'] else 'visible'
            if visibility:
                if visibility not in {'visible', 'archived', 'removed'}:
                    raise HTTPException(422, '无效可见性')
                record['visibility'] = visibility
            return store.put('history', identity, record)

    @router.patch('/api/history/{identity}/parameters')
    def edit_parameter(identity: str, body: dict):
        with run_lock(identity):
            record = enrich(get(identity))
            field, value = body.get('field'), body.get('value')
            if not isinstance(field, str) or not field or not isinstance(value, str):
                raise HTTPException(422, '参数名称和值必须为字符串')
            root = Path(record['cache_dir'])
            if not root.resolve().is_relative_to(cache_root) or (root / 'args.json').is_symlink():
                raise HTTPException(409, '缓存路径异常')
            if field in {'training', 'runtime'} or field in record['parameter_original_fields']:
                raise HTTPException(409, 'args 中已记录的超参数不可修改；仅能补充缺失字段')
            record.setdefault('parameter_annotations', {})[field] = value.strip()
            return store.put('history', identity, enrich(record))

    @router.delete('/api/history/{identity}')
    @router.post('/api/history/{identity}/remove')
    def remove(identity: str):
        with run_lock(identity):
            record = enrich(get(identity))
            record['visibility'] = 'removed'
            return store.put('history', identity, record)

    @router.get('/api/history/{identity}/export')
    def export(identity: str):
        with run_lock(identity):
            record = get(identity)
            root = Path(record['cache_dir'])
            if not root.resolve().is_relative_to(cache_root):
                raise HTTPException(409, '缓存路径异常')
            name = export_basename(record['name'], identity, set())
            data = io.BytesIO()
            actual = []
            with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(root.iterdir()) if root.exists() else []:
                    if file.name in ALLOWED_FILES and file.name != 'parameter_annotations.json' and file.is_file() and not file.is_symlink():
                        archive.write(file, f'{name}/{file.name}')
                        actual.append(file.name)
                if record.get('parameter_annotations'):
                    archive.writestr(f'{name}/parameter_annotations.json', json.dumps(record['parameter_annotations'], ensure_ascii=False, indent=2))
                    if 'parameter_annotations.json' not in actual:
                        actual.append('parameter_annotations.json')
                archive.writestr(f'{name}/export_manifest.json', json.dumps({
                    'id': identity, 'name': record['name'], 'status': record['status'],
                    'sync_status': record['sync_status'], 'files': actual, 'exported_at': time.time()}, ensure_ascii=False))
            from urllib.parse import quote
            return Response(data.getvalue(), media_type='application/zip', headers={
                'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name + '.zip')})

    def fingerprint(record):
        root = Path(record['cache_dir'])
        if root.is_symlink() or not root.resolve().is_relative_to(cache_root) or root.resolve() == cache_root:
            raise HTTPException(409, '缓存路径异常')
        if record.get('source', {}).get('kind') == 'local' and root.resolve() == Path(record['source']['path']).resolve():
            raise HTTPException(409, '缓存与原始导入目录相同，不能删除原始文件')
        files = []
        if root.exists():
            for path in root.rglob('*'):
                if path.is_symlink():
                    raise HTTPException(409, '缓存包含符号链接，拒绝删除')
                stat = path.stat()
                files.append((str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns, stat.st_ino))
        return str(root), sorted(files)

    @router.post('/api/history/{identity}/delete-preview')
    def preview(identity: str, body: dict):
        record = get(identity)
        run = store.get('runs', record.get('run_id') or identity)
        if (run or record).get('status') in {'running', 'stopping', 'queued', 'starting'}:
            raise HTTPException(409, '运行或排队中的实验不能永久删除')
        scope = body.get('scope', 'local')
        if scope not in {'local', 'remote', 'both'}:
            raise HTTPException(422, '无效删除范围')
        remote_preview = None
        if scope in {'remote', 'both'}:
            source = record['source']
            if source['kind'] != 'remote':
                raise HTTPException(422, '此实验没有远端来源')
            try:
                record.update(sync_history(record, cache_root))
                if record['sync_status'] != 'synced':
                    raise HTTPException(409, '最终记录尚未同步，请稍后重试')
                store.put('history', identity, record)
                remote_preview = rpc(source.get('ssh_alias', 'gpu'), 'delete_preview', {'path': source['path']})
            except (RuntimeError, OSError, ValueError) as exc:
                raise HTTPException(409, str(exc)) from exc
        path, files = fingerprint(record)
        token = secrets.token_urlsafe(32)
        store.put('deletion_previews', token, {'id': token, 'history_id': identity,
            'path': path, 'files': files, 'scope': scope, 'remote_preview': remote_preview, 'expires_at': time.time() + 120})
        targets = ([path] if scope in {'local', 'both'} else []) + (remote_preview['targets'] if remote_preview else [])
        size = (sum(f[1] for f in files) if scope in {'local', 'both'} else 0) + ((remote_preview or {}).get('bytes', 0))
        return {'confirmation_token': token, 'targets': targets, 'scope': scope, 'bytes': size, 'expires_at': time.time() + 120}

    @router.post('/api/history/{identity}/delete-confirm')
    def confirm(identity: str, body: dict):
        with run_lock(identity):
            token = body.get('confirmation_token', '')
            saved = store.get('deletion_previews', token)
            if not saved or saved['history_id'] != identity or saved['expires_at'] < time.time():
                raise HTTPException(409, '删除确认已失效，请重新预览')
            record = get(identity)
            run = store.get('runs', record.get('run_id') or identity)
            if (run or record).get('status') in {'running', 'stopping', 'queued', 'starting'}:
                raise HTTPException(409, '实验仍在运行或排队')
            path, files = fingerprint(record)
            if path != saved['path'] or json.dumps(files) != json.dumps(saved['files']):
                raise HTTPException(409, '文件已变化，请重新预览')
            scope = saved.get('scope', 'local')
            targets = []
            if saved.get('remote_preview'):
                try:
                    response = rpc(record['source'].get('ssh_alias', 'gpu'), 'delete_confirm',
                                   {'confirmation_token': saved['remote_preview']['confirmation_token']})
                    targets.extend(response['targets'])
                except (RuntimeError, OSError, ValueError) as exc:
                    raise HTTPException(409, str(exc)) from exc
                record['remote_deleted'] = True
            if scope in {'local', 'both'}:
                if Path(path).exists():
                    shutil.rmtree(path)
                targets.append(path)
                record.update(visibility='removed', sync_status='deleted')
            else:
                record['sync_status'] = 'synced'
            store.put('history', identity, record)
            store.delete('deletion_previews', token)
            return {'deleted': True, 'targets': targets}

    from ai_exp_app.analysis.api import create_router as analysis_router
    router.include_router(analysis_router(store))
    return router
