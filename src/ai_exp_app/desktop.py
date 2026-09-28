"""Single-instance localhost service launched by the macOS entry app."""
import fcntl
import json
import os
from pathlib import Path
import urllib.request
import uvicorn
from ai_exp_app.app import create_app
from ai_exp_app.config import Config


def is_our_service(value):
    return value.get("app") == "ai-exp-app" and bool(value.get("instance_id"))


def main():
    config = Config.load()
    with (config.data_dir / "service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{config.port}/api/health", timeout=1) as response:
                if is_our_service(json.load(response)):
                    return
                raise RuntimeError("端口由其他应用占用")
        except urllib.error.URLError:
            pass
        app = create_app()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.port, log_level="info"))
        app.state.shutdown = lambda: setattr(server, "should_exit", True)
        identity = {"pid": os.getpid(), "instance_id": app.state.instance_id, "url": f"http://127.0.0.1:{config.port}", "root": str(Path(__file__).resolve().parents[2])}
        path = config.data_dir / "service.json"
        path.write_text(json.dumps(identity))
        path.chmod(0o600)
        try:
            server.run()
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
