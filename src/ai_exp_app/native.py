"""Windows/Linux native window around the shared, authenticated localhost service."""
import ctypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import plistlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import tempfile
import socket
from dataclasses import replace
from urllib.parse import urlsplit
import time
import urllib.request
from ai_exp_app.config import Config
from ai_exp_app.locking import FileLock
from ai_exp_app.platform_runtime import LOCAL_HTTP, start_service


def focus_existing(config, timeout=4, path="/focus"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            identity = json.loads((config.data_dir/'native.json').read_text(encoding='utf-8'))
            port = identity['port']
            if not isinstance(port,int) or not 0 < port < 65536:
                raise ValueError('invalid focus port')
            request = urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=b'{}',method='POST',
                                             headers={'X-Native-Focus':identity['token']})
            with LOCAL_HTTP.open(request,timeout=1) as response:
                if json.load(response).get('ok'):
                    return True
        except (OSError,ValueError,KeyError):
            time.sleep(.1)
    raise RuntimeError('已有桌面窗口尚未响应，请稍后重试')


class FocusServer:
    def __init__(self, config, focus, close=None):
        self.config, self.token = config,secrets.token_urlsafe(32)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path not in ('/focus','/close') or self.headers.get('Origin') or not secrets.compare_digest(self.headers.get('X-Native-Focus',''),owner.token):
                    self.send_error(403)
                    return
                if self.path=='/close':
                    if close is None:
                        self.send_error(404)
                        return
                    close()
                else:
                    focus()
                data = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self,*args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        path = config.data_dir/'native.json'
        path.write_text(json.dumps({'port':self.server.server_port,'token':self.token,'pid':os.getpid()}),encoding='utf-8')
        path.chmod(0o600)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        path = self.config.data_dir/'native.json'
        try:
            if json.loads(path.read_text(encoding="utf-8")).get('token') == self.token:
                path.unlink()
        except (OSError,ValueError):
            pass


def hide_own_windows_console():
    if sys.platform != 'win32' or not getattr(sys,'frozen',False):
        return
    kernel = ctypes.windll.kernel32
    processes = (ctypes.c_uint32*2)()
    if kernel.GetConsoleProcessList(processes,2) == 1:
        handle = kernel.GetConsoleWindow()
        if handle:
            ctypes.windll.user32.ShowWindow(handle,0)


class Desktop:
    def __init__(self, config, origin, webview, smoke_test=None):
        self.config,self.origin,self.webview = config,origin,webview
        self.smoke_test = Path(smoke_test) if smoke_test else None
        self.window = None
        self.closed = threading.Event()
        self.focus_pending = threading.Event()
        self.close_pending = threading.Event()
        self.loaded = threading.Event()
        self.failure = None
        self._notify_icon = None

    def request(self,path,body=None):
        token = (self.config.data_dir/'desktop-token').read_text(encoding='utf-8').strip()
        headers = {'X-Desktop-Token':token}
        data = None
        if body is not None:
            headers['Content-Type']='application/json'
            data=json.dumps(body).encode()
        with LOCAL_HTTP.open(urllib.request.Request(self.origin+path,data=data,headers=headers),timeout=3) as response:
            return json.load(response)

    def focus(self):
        self.focus_pending.set()

    def request_close(self):
        self.close_pending.set()

    def notification_settings(self):
        if not self.window or self.window.get_current_url().split('/',3)[:3] != self.origin.split('/'):
            raise RuntimeError('仅允许工作台打开系统设置')
        if sys.platform == 'win32':
            os.startfile('ms-settings:notifications')
            return '已打开 Windows 系统通知设置'
        commands=[['gnome-control-center','notifications'],['systemsettings','kcm_notifications'],['systemsettings5','kcm_notifications']]
        if 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP','').upper():
            commands=commands[1:]+commands[:1]
        for command in commands:
            if shutil.which(command[0]):
                subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                return '已打开系统通知设置'
        self.window.create_confirmation_dialog('系统通知','请在桌面环境的系统设置中开启应用通知；实验状态也会保存在工作台通知中心。')
        return '请在系统设置中允许通知'

    def configure_window(self):
        self.configure_qt_downloads()
        if sys.platform == 'win32':
            from System.Drawing import Icon,SystemIcons
            from System.Windows.Forms import NotifyIcon
            self._notify_icon=NotifyIcon()
            icon=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))/'native'/'AppIcon.ico'
            self._notify_icon.Icon=Icon(str(icon)) if icon.exists() else SystemIcons.Application
            self._notify_icon.Text='AI Experiment'
            self._notify_icon.Click += lambda *_:self.focus()
            self._notify_icon.Visible=True

    def deliver_notification(self,item):
        title=str(item.get('title') or 'Experiment update')
        body=str(item.get('body') or 'Open AI Experiment to see the current status.')
        if sys.platform == 'win32':
            if self._notify_icon is None:
                return False
            from System import Action
            from System.Windows.Forms import ToolTipIcon
            finished=threading.Event()
            def show():
                if not self.closed.is_set():
                    self._notify_icon.ShowBalloonTip(5000,title[:63],body[:255],ToolTipIcon.Info)
                    finished.set()
            self.window.native.BeginInvoke(Action(show))
            return finished.wait(3)
        if shutil.which('notify-send'):
            result=subprocess.run(['notify-send','--app-name=AI Experiment','--',title,body],
                                  capture_output=True,timeout=5)
            return result.returncode==0
        return False

    def close(self):
        self.closed.set()
        if self._notify_icon is not None:
            self._notify_icon.Dispose()

    def configure_qt_downloads(self):
        if not sys.platform.startswith('linux'):
            return
        # Qt 6 replaced the Qt 5 setPath method used by some pywebview versions.
        from PySide6.QtWidgets import QFileDialog
        view = self.window.native.webview
        signal = view.page().profile().downloadRequested
        signal.disconnect()
        def download(item):
            suggested = item.suggestedFileName() or 'download'
            target,_ = QFileDialog.getSaveFileName(self.window.native,'保存文件',str(Path.home()/'Downloads'/Path(suggested).name))
            if target:
                path=Path(target)
                item.setDownloadDirectory(str(path.parent))
                item.setDownloadFileName(path.name)
                item.accept()
            else:
                item.cancel()
        signal.connect(download)
        self.download_callback=download

    def smoke(self):
        deadline=time.monotonic()+25
        try:
            while not self.closed.is_set() and time.monotonic()<deadline:
                if self.loaded.is_set():
                    result=self.window.evaluate_js('JSON.stringify({title:document.title,href:location.href,children:document.querySelector("#root")?.childElementCount||0,text:document.body.innerText})')
                    value=json.loads(result) if isinstance(result,str) else result
                    if isinstance(value,dict) and value.get('children',0)>0 and value.get('href','').startswith(self.origin+'/'):
                        value.update(ok=True,renderer='edgechromium' if sys.platform=='win32' else 'qt',platform=sys.platform)
                        self.smoke_test.parent.mkdir(parents=True,exist_ok=True)
                        self.smoke_test.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
                        return
                time.sleep(.2)
            raise RuntimeError('原生窗口未在限定时间内加载工作台')
        except Exception as exc:
            self.failure=exc
            self.smoke_test.parent.mkdir(parents=True,exist_ok=True)
            self.smoke_test.write_text(json.dumps({'ok':False,'error':str(exc)}),encoding='utf-8')
        finally:
            self.window.destroy()

    def run(self):
        if self.smoke_test:
            threading.Thread(target=self.smoke,daemon=True).start()
        while not self.closed.is_set():
            if self.close_pending.is_set():
                self.window.destroy()
                return
            if self.focus_pending.is_set():
                self.focus_pending.clear()
                self.window.restore()
                self.window.show()
            try:
                # Heartbeat keeps browser clients' native folder picker available.
                notifications=self.request('/api/desktop/notifications')
                for item in notifications:
                    try:
                        if self.deliver_notification(item):
                            self.request('/api/desktop/notifications/'+item['id']+'/delivered',{})
                    except Exception:
                        pass  # Preserve the in-app record when OS delivery is unavailable.
                picker=self.request('/api/desktop/picker')
                if picker:
                    selected=self.window.create_file_dialog(self.webview.FileDialog.FOLDER,allow_multiple=False)
                    self.request('/api/desktop/picker/'+picker['id'],{'path':selected[0]} if selected else {})
            except (OSError,ValueError):
                pass
            self.closed.wait(3)


class NativeAPI:
    def __init__(self, desktop):
        self._desktop=desktop

    def notification_settings(self):
        return self._desktop.notification_settings()


def find_macos_app():
    candidates=[parent for parent in Path(sys.executable).resolve().parents if parent.suffix=='.app']
    candidates += [Path('/Applications/AI Experiment.app'),Path.home()/'Applications/AI Experiment.app']
    for app in candidates:
        try:
            info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
            if info.get('CFBundleIdentifier')=='org.ai-experiment.workbench' and (app/'Contents/MacOS/AIExperiment').is_file():
                return app
        except (OSError,ValueError):
            pass
    raise RuntimeError('请先下载并安装 macOS 桌面应用：https://github.com/Bruce-lhq/ai-exp-app/releases')


def launch_macos(config,smoke_test=None):
    app=find_macos_app()
    if not smoke_test:
        subprocess.run(['/usr/bin/open','-a',str(app)],check=True)
        return
    # Invoke a separate process directly, never reopen or reconfigure a user's app.
    from ai_exp_app.platform_runtime import service_status,stop_service
    with tempfile.TemporaryDirectory(prefix='ai-exp-native-smoke-') as temp:
        data=Path(temp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        isolated=replace(config,data_dir=data,cache_root=data/'cache',config_file=data/'config.local.json',port=port)
        report=Path(smoke_test).resolve();report.parent.mkdir(parents=True,exist_ok=True)
        report.unlink(missing_ok=True)
        env=dict(os.environ,AI_EXP_DATA_DIR=str(data),AI_EXP_CACHE_ROOT=str(data/'cache'),AI_EXP_CONFIG_FILE=str(data/'config.local.json'),
                 AI_EXP_PORT=str(port),AI_EXP_NATIVE_SMOKE_PATH=str(report))
        with (data/'native.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([str(app/'Contents/MacOS/AIExperiment')],env=env,stdout=log,stderr=log)
            try:
                process.wait(timeout=45)
                if not report.exists() or not json.loads(report.read_text(encoding='utf-8')).get('ok'):
                    raise RuntimeError('原生窗口验收失败：'+(data/'native.log').read_text(encoding='utf-8')[-2000:])
            finally:
                if process.poll() is None:
                    process.terminate();process.wait(timeout=5)
                if service_status(isolated):stop_service(isolated)


class ProcessExit:
    """Wait on an already captured Windows process handle; never terminate it."""
    def __init__(self,pid):
        self.handle=None
        if os.name=='nt':
            from ctypes import wintypes
            self.kernel=ctypes.windll.kernel32
            self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            self.kernel.OpenProcess.restype=wintypes.HANDLE
            self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
            self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            self.handle=self.kernel.OpenProcess(0x00100000,False,int(pid))
            if not self.handle:raise RuntimeError('不能确认应用进程已经退出；请先关闭桌面和 CLI 命令')

    def wait(self,timeout=10):
        try:
            if self.handle and self.kernel.WaitForSingleObject(self.handle,int(timeout*1000))!=0:
                raise RuntimeError('应用仍在退出，请稍后再安装或卸载')
        finally:self.close()

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle=None


def lock_available(path):
    try:
        with FileLock(path):return True
    except BlockingIOError:return False


def prepare_installation(config=None):
    """Release this workspace's files through private APIs before replacement."""
    from ai_exp_app.platform_runtime import service_status,stop_service
    config=config or Config.load()
    if not lock_available(config.data_dir/'native.lock'):
        identity=json.loads((config.data_dir/'native.json').read_text(encoding='utf-8'))
        process=ProcessExit(identity['pid'])
        try:
            focus_existing(config,path='/close')
            deadline=time.monotonic()+20
            while not lock_available(config.data_dir/'native.lock'):
                if time.monotonic()>=deadline:raise RuntimeError('请先关闭桌面窗口、完成目录选择，再重试')
                time.sleep(.1)
            process.wait()
        finally:process.close()
    if not lock_available(config.data_dir/'service.lock'):
        record=json.loads((config.data_dir/'service.json').read_text(encoding='utf-8'))
        url=urlsplit(record['url'])
        if url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.path or url.query or url.fragment:
            raise RuntimeError('服务身份无效；请通过 CLI 检查自己的工作空间')
        config=replace(config,port=url.port)
        identity=service_status(config)
        if not identity:raise RuntimeError('本地服务尚未响应；请稍后重试')
        process=ProcessExit(identity['pid'])
        try:
            stop_service(config)
            process.wait()
        finally:process.close()
    return {'ready':True}


def main(config=None, *, smoke_test=None):
    config=config or Config.load()
    if sys.platform=="darwin":
        launch_macos(config,smoke_test)
        return
    hide_own_windows_console()
    lock=FileLock(config.data_dir/'native.lock')
    try:
        lock.__enter__()
    except BlockingIOError:
        focus_existing(config)
        return
    ipc=None
    try:
        # GUI imports stay out of CLI/service commands and require no display there.
        if sys.platform.startswith('linux'):
            os.environ['QT_API']='pyside6'
        import webview
        command=[sys.executable,'service','run'] if getattr(sys,'frozen',False) else None
        desktop=Desktop(config,f'http://127.0.0.1:{config.port}',webview,smoke_test)
        ipc=FocusServer(config,desktop.focus,desktop.request_close)
        service=start_service(config,command=command)
        if desktop.close_pending.is_set():
            return
        webview.settings.update(ALLOW_DOWNLOADS=True,ALLOW_FILE_URLS=False,OPEN_EXTERNAL_LINKS_IN_BROWSER=True)
        desktop.window=webview.create_window('AI Experiment',service['url']+'/',js_api=NativeAPI(desktop),width=1380,height=920,min_size=(900,650))
        desktop.window.events.loaded += desktop.loaded.set
        desktop.window.events.closed += desktop.close
        desktop.window.events.before_show += desktop.configure_window
        icon=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[2]))/'native'/('AppIcon.ico' if sys.platform=='win32' else 'AppIcon.png')
        webview.start(desktop.run,gui='edgechromium' if sys.platform=='win32' else 'qt',private_mode=True,icon=str(icon) if icon.exists() else None)
        if desktop.failure:
            raise desktop.failure
    finally:
        if ipc:
            ipc.close()
        lock.__exit__(None,None,None)
        # The localhost service remains available to other desktop/browser/CLI users.
