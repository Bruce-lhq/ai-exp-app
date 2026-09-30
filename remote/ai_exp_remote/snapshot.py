import fnmatch
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import uuid
from .state import AgentError

EXCLUDED = {'.git', '.venv', '__pycache__', 'node_modules', '.cache'}

def excluded(path, exclusions):
    return any(p in EXCLUDED for p in path.parts) or any(fnmatch.fnmatch(str(path), p) for p in exclusions)

def manifest(root, exclusions):
    result = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if excluded(rel, exclusions):
            continue
        if path.is_symlink():
            raise AgentError('SNAPSHOT_SYMLINK', '代码快照不支持符号链接', str(rel))
        if path.is_file():
            if path.stat().st_size > 50 * 1024 * 1024:
                raise AgentError('SNAPSHOT_LARGE_FILE', '请将数据/权重移出代码目录或明确排除', str(rel))
            result[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def create_snapshot(source, destination, code, exclusions):
    source, destination = Path(source).resolve(), Path(destination)
    staging = destination.parent / ('.staging-' + str(uuid.uuid4()))
    staging.mkdir(parents=True)
    commit = None
    dirty = False
    try:
        if (source / '.git').exists():
            ref = code.get('ref') if code.get('kind') != 'working_tree' else 'HEAD'
            commit = subprocess.check_output(['git','-C',str(source),'rev-parse','--verify',str(ref or 'HEAD')+'^{commit}'], text=True).strip()
            dirty = bool(subprocess.check_output(['git','-C',str(source),'status','--porcelain'], text=True))
        if code.get('kind') in ('ref','branch','commit'):
            if not commit:
                raise AgentError('NOT_GIT', '普通目录不支持分支选择')
            data = subprocess.check_output(['git','-C',str(source),'archive',commit])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                for member in archive.getmembers():
                    if member.issym() or member.islnk() or member.name.startswith('/') or '..' in Path(member.name).parts:
                        raise AgentError('SNAPSHOT_SYMLINK', 'Git 快照包含不安全链接')
                archive.extractall(staging, members=[m for m in archive.getmembers() if not excluded(Path(m.name), exclusions)])
        else:
            before = manifest(source, exclusions)
            for name in before:
                dest = staging / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, dest)
            if before != manifest(source, exclusions) or before != manifest(staging, []):
                raise AgentError('SOURCE_CHANGED', '复制期间代码发生变化，请重试')
        files = manifest(staging, [])
        fingerprint = hashlib.sha256(repr(sorted(files.items())).encode()).hexdigest()
        staging.rename(destination)
        return dict(id=fingerprint, path=str(destination), manifest=files, commit=commit, dirty=dirty)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
