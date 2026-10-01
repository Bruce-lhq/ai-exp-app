import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error
import urllib.request
import pytest
from ai_exp_app.native import Desktop,FocusServer,NativeAPI,focus_existing,main
from ai_exp_app.platform_runtime import LOCAL_HTTP


def test_single_instance_focus_requires_private_token(tmp_path):
    config=SimpleNamespace(data_dir=tmp_path)
    calls=[]
    server=FocusServer(config,lambda:calls.append('focus'))
    try:
        identity=json.loads((tmp_path/'native.json').read_text())
        for headers in ({},{'X-Native-Focus':identity['token'],'Origin':'http://malicious.invalid'}):
            request=urllib.request.Request(f'http://127.0.0.1:{identity["port"]}/focus',data=b'{}',headers=headers)
            with pytest.raises(urllib.error.HTTPError) as error:
                LOCAL_HTTP.open(request)
            assert error.value.code==403
        assert focus_existing(config)
        assert calls==['focus']
    finally:
        server.close()
    assert not (tmp_path/'native.json').exists()


def test_javascript_bridge_exposes_no_service_token_or_arbitrary_request():
    api=NativeAPI(SimpleNamespace(notification_settings=lambda:'settings'))
    public=[name for name in dir(api) if not name.startswith('_')]
    assert public==['notification_settings']
    assert api.notification_settings()=='settings'


def test_native_settings_reject_foreign_document(tmp_path):
    desktop=Desktop(SimpleNamespace(data_dir=tmp_path),'http://127.0.0.1:9999',None)
    desktop.window=SimpleNamespace(get_current_url=lambda:'https://foreign.example/')
    with pytest.raises(RuntimeError,match='仅允许工作台'):
        desktop.notification_settings()


def test_native_smoke_requires_rendered_application_and_records_errors(tmp_path):
    desktop=Desktop(SimpleNamespace(data_dir=tmp_path),'http://127.0.0.1:9999',None,tmp_path/'result.json')
    destroyed=[]
    desktop.window=SimpleNamespace(evaluate_js=lambda _:json.dumps({'title':'AI Experiment','href':desktop.origin+'/','children':1,'text':'运行监控'}),destroy=lambda:destroyed.append(True))
    desktop.loaded.set()
    desktop.smoke()
    result=json.loads((tmp_path/'result.json').read_text())
    assert result['ok'] is True
    assert destroyed==[True]
    assert desktop.failure is None


def test_native_reopen_focuses_existing_window_without_starting_service(tmp_path,monkeypatch):
    class HeldLock:
        def __init__(self,path):pass
        def __enter__(self):raise BlockingIOError()
    calls=[]
    monkeypatch.setattr('ai_exp_app.native.FileLock',HeldLock)
    monkeypatch.setattr('ai_exp_app.native.focus_existing',lambda config:calls.append('focus'))
    monkeypatch.setattr('ai_exp_app.native.start_service',lambda *a,**k:pytest.fail('must not start another service'))
    main(SimpleNamespace(data_dir=tmp_path))
    assert calls==['focus']


def test_native_smoke_failure_still_destroys_only_window(tmp_path):
    desktop=Desktop(SimpleNamespace(data_dir=tmp_path),'http://127.0.0.1:9999',None,tmp_path/'result.json')
    destroyed=[]
    desktop.window=SimpleNamespace(evaluate_js=lambda _:(_ for _ in ()).throw(ValueError('failed js')),destroy=lambda:destroyed.append(True))
    desktop.loaded.set()
    desktop.smoke()
    assert json.loads((tmp_path/'result.json').read_text())['ok'] is False
    assert destroyed==[True]


def test_failed_os_notifications_stay_available_in_app(tmp_path):
    desktop=Desktop(SimpleNamespace(data_dir=tmp_path),'http://127.0.0.1:9999',None)
    calls=[]
    def request(path,body=None):
        calls.append(path)
        if path=='/api/desktop/notifications':return [{'id':'one','title':'Stopped'}]
        if path=='/api/desktop/picker':desktop.closed.set();return None
    desktop.request=request
    desktop.deliver_notification=lambda item:False
    desktop.run()
    assert not any('/delivered' in path for path in calls)


def test_successful_os_notifications_are_acknowledged(tmp_path):
    desktop=Desktop(SimpleNamespace(data_dir=tmp_path),'http://127.0.0.1:9999',None)
    calls=[]
    def request(path,body=None):
        calls.append(path)
        if path=='/api/desktop/notifications':return [{'id':'one','title':'Stopped'}]
        if path=='/api/desktop/picker':desktop.closed.set();return None
    desktop.request=request
    desktop.deliver_notification=lambda item:True
    desktop.run()
    assert '/api/desktop/notifications/one/delivered' in calls


def test_linux_notifications_pass_literal_argv_and_report_provider_failure(tmp_path,monkeypatch):
    import ai_exp_app.native as native
    monkeypatch.setattr(native.sys,'platform','linux')
    monkeypatch.setattr(native.shutil,'which',lambda name:'/usr/bin/notify-send')
    calls=[]
    monkeypatch.setattr(native.subprocess,'run',lambda argv,**kwargs:calls.append(argv) or SimpleNamespace(returncode=1))
    desktop=Desktop(SimpleNamespace(data_dir=tmp_path),'http://127.0.0.1:9999',None)
    assert desktop.deliver_notification({'title':'--$(touch x)','body':'body'}) is False
    assert calls==[['notify-send','--app-name=AI Experiment','--','--$(touch x)','body']]


def test_windows_notifications_marshal_to_live_window_loop(tmp_path,monkeypatch):
    import ai_exp_app.native as native
    monkeypatch.setattr(native.sys,'platform','win32')
    monkeypatch.setitem(native.sys.modules,'System',SimpleNamespace(Action=lambda callback:callback))
    monkeypatch.setitem(native.sys.modules,'System.Windows.Forms',SimpleNamespace(ToolTipIcon=SimpleNamespace(Info='info')))
    desktop=Desktop(SimpleNamespace(data_dir=tmp_path),'http://127.0.0.1:9999',None)
    calls=[]
    desktop._notify_icon=SimpleNamespace(ShowBalloonTip=lambda *args:calls.append(args))
    desktop.window=SimpleNamespace(native=SimpleNamespace(BeginInvoke=lambda callback:callback()))
    assert desktop.deliver_notification({'title':'Done','body':'Completed'}) is True
    assert calls==[(5000,'Done','Completed','info')]
