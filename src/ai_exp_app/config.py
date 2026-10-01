from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
LOCAL_DEFAULTS = {
    'ssh_alias': 'gpu',
    'remote_agent': '.local/share/ai-exp-app/agent.pyz',
    'remote_root': '.local/share/ai-exp-app',
    'remote_state_dir': '',
    'remote_python': 'python3',
    'remote_gpu_probe': '',
    'remote_runs_root': '',
    'remote_data_root': '',
    'remote_projects_root': '/',
    'remote_groups_root': '',
    'remote_import_root': '/',
    'local_import_root': '~/gpu_downloads/',
}


@dataclass(frozen=True)
class Config:
    data_dir: Path
    cache_root: Path
    web_root: Path = ROOT / 'web' / 'dist'
    port: int = 8765
    config_file: Path = ROOT / 'config.local.json'

    @property
    def local_settings(self):
        document = json.loads(self.config_file.read_text(encoding='utf-8')) if self.config_file.exists() else {}
        if not isinstance(document, dict):
            raise ValueError('config.local.json 必须为 JSON 对象')
        return {**LOCAL_DEFAULTS, **{key: document[key] for key in LOCAL_DEFAULTS if key in document}}

    @property
    def configured(self):
        value = self.local_settings
        return self.config_file.exists() and all(value[key] for key in ('ssh_alias', 'remote_agent', 'remote_python')) and str(value['remote_runs_root']).startswith('/')

    def save_local_settings(self, values):
        unknown = set(values) - set(LOCAL_DEFAULTS)
        if unknown:
            raise ValueError('未知配置项：' + ', '.join(sorted(unknown)))
        if any(not isinstance(value, str) or '\0' in value for value in values.values()):
            raise ValueError('配置项必须为不含空字符的字符串')
        previous = self.local_settings
        document = {**previous, **{key: value.strip() for key, value in values.items()}}
        if document['remote_root'] != previous['remote_root'] and document['remote_agent'] == previous['remote_agent'] == previous['remote_root'].rstrip('/') + '/agent.pyz':
            document['remote_agent'] = document['remote_root'].rstrip('/') + '/agent.pyz'
        if document['remote_runs_root'] != previous['remote_runs_root'] and document['remote_import_root'] in {'/', previous['remote_runs_root'].rstrip('/') + '/'}:
            document['remote_import_root'] = document['remote_runs_root'].rstrip('/') + '/' if document['remote_runs_root'] else '/'

        if not re.fullmatch(r'[A-Za-z0-9_.-]+', document['ssh_alias']) or document['ssh_alias'].startswith('-'):
            raise ValueError('SSH 别名无效')
        if any('\n' in document[key] for key in ('remote_agent', 'remote_python', 'remote_root')):
            raise ValueError('远端命令和路径不能包含换行')
        if document['remote_runs_root'] == '/':
            raise ValueError('实验根目录必须为专用目录，不能是 /')
        for key in ('remote_runs_root', 'remote_data_root', 'remote_projects_root', 'remote_import_root', 'remote_state_dir', 'remote_groups_root', 'remote_gpu_probe'):
            if document[key] and not document[key].startswith('/'):
                raise ValueError(key + ' 必须为远端绝对目录')
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(self.config_file)
        return document

    @classmethod
    def load(cls, data_dir: Path | None = None):
        installed = platform_data_dir()
        legacy = ROOT / '.local'
        if (installed / 'app.sqlite3').exists() or (installed / 'config.local.json').exists():
            default = installed
        elif (legacy / 'app.sqlite3').exists() or (ROOT / 'config.local.json').exists():
            default = legacy
        else:
            default = installed
        directory = Path(data_dir or os.environ.get('AI_EXP_DATA_DIR', default)).expanduser().resolve()
        cache_default = ROOT / 'gpu_downloads' if directory == ROOT / '.local' else directory / 'gpu_downloads'
        config_default = ROOT / 'config.local.json' if directory == ROOT / '.local' else directory / 'config.local.json'
        path = Path(os.environ.get('AI_EXP_CONFIG_FILE', config_default)).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        cache = Path(os.environ.get('AI_EXP_CACHE_ROOT', cache_default)).expanduser().resolve()
        return cls(directory, cache, web_root=Path(os.environ.get('AI_EXP_WEB_ROOT', ROOT / 'web' / 'dist')).resolve(), port=int(os.environ.get('AI_EXP_PORT', '8765')), config_file=path)


def platform_data_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'AI Experiment'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'AI Experiment'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'ai-exp-app'


def local_settings(store=None):
    config = getattr(store, 'config', None) or Config.load()
    return config.local_settings
