"""Single-instance localhost service shared by desktop and CLI entry points."""
import json
import os
from pathlib import Path
import uvicorn
from ai_exp_app.app import create_app
from ai_exp_app.config import Config
from ai_exp_app.locking import FileLock
from ai_exp_app.platform_runtime import health, is_our_service


def main():
    config = Config.load()
    try:
        with FileLock(config.data_dir / 'service.lock'):
            if health(f'http://127.0.0.1:{config.port}') is not None:
                raise RuntimeError('端口已被另一个工作台占用')
            app = create_app(config.data_dir)
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=config.port, log_level='info'))
            app.state.shutdown = lambda: setattr(server, 'should_exit', True)
            identity = {'pid': os.getpid(), 'instance_id': app.state.instance_id,
                        'url': f'http://127.0.0.1:{config.port}', 'root': str(Path(__file__).resolve().parents[2])}
            path = config.data_dir / 'service.json'
            path.write_text(json.dumps(identity), encoding='utf-8')
            path.chmod(0o600)
            try:
                server.run()
            finally:
                path.unlink(missing_ok=True)
    except BlockingIOError:
        return


if __name__ == '__main__':
    main()
