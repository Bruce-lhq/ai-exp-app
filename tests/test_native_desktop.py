import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error
import urllib.request
import pytest
from ai_exp_app.native import Desktop,FocusServer,NativeAPI,focus_existing,main
from ai_exp_app.platform_runtime import LOCAL_HTTP


@pytest.mark.parametrize('platform,extension,renderer',[('win32','ico','edgechromium'),('linux','png','qt')])
def test_native_renderer_receives_platform_icon(tmp_path,monkeypatch,platform,extension,renderer):
    import ai_exp_app.native as native
    monkeypatch.setattr(native.sys,'platform',platform)
    monkeypatch.setattr(native.sys,'_MEIPASS',str(tmp_path),raising=False)
    monkeypatch.setattr(native,'hide_own_windows_console',lambda:None)
    monkeypatch.setattr(native,'FocusServer',lambda *args:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(native,'start_service',lambda *a,**k:{'url':'http://127.0.0.1:9999'})
    class Event:
        def __iadd__(self,handler):return self
    window=SimpleNamespace(events=SimpleNamespace(loaded=Event(),closed=Event(),before_show=Event()))
    calls=[]
    monkeypatch.setitem(native.sys.modules,'webview',SimpleNamespace(settings={},create_window=lambda *a,**k:window,start=lambda *a,**k:calls.append(k)))
    (tmp_path/'native').mkdir()
    for suffix in ('ico','png'):(tmp_path/'native'/('AppIcon.'+suffix)).write_bytes(b'icon')
    main(SimpleNamespace(data_dir=tmp_path,port=9999))
    assert calls[0]['gui']==renderer
    assert calls[0]['icon']==str(tmp_path/'native'/('AppIcon.'+extension))


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
    monkeypatch.setattr('ai_exp_app.native.sys.platform','linux')
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


def test_macos_desktop_uses_swift_app_without_importing_webview(tmp_path,monkeypatch):
    import ai_exp_app.native as native
    monkeypatch.setattr(native.sys,'platform','darwin')
    app=tmp_path/'AI Experiment.app'
    monkeypatch.setattr(native,'find_macos_app',lambda:app)
    calls=[]
    monkeypatch.setattr(native.subprocess,'run',lambda argv,**kwargs:calls.append(argv))
    main(SimpleNamespace(data_dir=tmp_path))
    assert calls==[['/usr/bin/open','-a',str(app)]]


def test_macos_app_discovery_prefers_matching_bundle_around_cli(tmp_path,monkeypatch):
    import plistlib
    import ai_exp_app.native as native
    app=tmp_path/'AI Experiment.app'
    binary=app/'Contents/MacOS/AIExperiment';binary.parent.mkdir(parents=True);binary.write_bytes(b'not run')
    cli=app/'Contents/Resources/server/ai-experiment';cli.parent.mkdir(parents=True);cli.write_bytes(b'not run')
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.ai-experiment.workbench'}))
    monkeypatch.setattr(native.sys,'executable',str(cli))
    assert native.find_macos_app()==app


def test_macos_cli_smoke_never_uses_personal_workspace(tmp_path,monkeypatch):
    import ai_exp_app.native as native
    from ai_exp_app.config import Config
    app=tmp_path/'AI Experiment.app'
    personal=tmp_path/'personal';personal.mkdir()
    (personal/'marker').write_text('preserve')
    report=tmp_path/'report.json'
    config=Config(personal,personal/'cache',tmp_path/'web',8765,personal/'config.local.json')
    monkeypatch.setattr(native,'find_macos_app',lambda:app)
    monkeypatch.setattr('ai_exp_app.platform_runtime.service_status',lambda config:None)
    values={}
    class Process:
        def __init__(self,argv,env,**kwargs):values.update(env=env,argv=argv)
        def wait(self,timeout):Path(values['env']['AI_EXP_NATIVE_SMOKE_PATH']).write_text('{"ok":true}')
        def poll(self):return 0
    monkeypatch.setattr(native.subprocess,'Popen',Process)
    native.launch_macos(config,report)
    assert Path(values['env']['AI_EXP_DATA_DIR'])!=personal
    assert values['env']['AI_EXP_PORT']!='8765'
    assert sorted(p.name for p in personal.iterdir())==['marker']
    assert report.exists()


def test_authenticated_close_request_closes_only_its_native_window(tmp_path):
    config=SimpleNamespace(data_dir=tmp_path)
    calls=[]
    server=FocusServer(config,lambda:calls.append('focus'),lambda:calls.append('close'))
    try:
        focus_existing(config,path='/close')
        assert calls==['close']
    finally:server.close()


def test_installer_never_contacts_unrelated_service_without_owned_lock(tmp_path,monkeypatch):
    import ai_exp_app.native as native
    from ai_exp_app.config import Config
    config=Config(tmp_path,tmp_path/'cache')
    monkeypatch.setattr('ai_exp_app.platform_runtime.service_status',lambda config:pytest.fail('unrelated service must not be probed'))
    monkeypatch.setattr('ai_exp_app.platform_runtime.stop_service',lambda config:pytest.fail('unrelated service must not be stopped'))
    assert native.prepare_installation(config)=={'ready':True}


def test_installer_stops_verified_service_on_its_recorded_port(tmp_path,monkeypatch):
    import ai_exp_app.native as native
    from ai_exp_app.config import Config
    config=Config(tmp_path,tmp_path/'cache',port=8765)
    (tmp_path/'service.json').write_text(json.dumps({'url':'http://127.0.0.1:9998','pid':42}),encoding='utf-8')
    monkeypatch.setattr(native,'lock_available',lambda path:path.name=='native.lock')
    calls=[]
    monkeypatch.setattr('ai_exp_app.platform_runtime.service_status',lambda config:calls.append(('verify',config.port)) or {'pid':42})
    monkeypatch.setattr('ai_exp_app.platform_runtime.stop_service',lambda config:calls.append(('stop',config.port)))
    class Exit:
        def __init__(self,pid):calls.append(('capture',pid))
        def wait(self):calls.append(('wait',None))
        def close(self):pass
    monkeypatch.setattr(native,'ProcessExit',Exit)
    assert native.prepare_installation(config)=={'ready':True}
    assert calls==[('verify',9998),('capture',42),('stop',9998),('wait',None)]


def test_installer_rejects_foreign_service_identity_and_keeps_files(tmp_path,monkeypatch):
    import ai_exp_app.native as native
    from ai_exp_app.config import Config
    config=Config(tmp_path,tmp_path/'cache')
    (tmp_path/'service.json').write_text(json.dumps({'url':'http://127.0.0.1:9998','pid':42}),encoding='utf-8')
    (tmp_path/'preserve').write_text('application/data')
    monkeypatch.setattr(native,'lock_available',lambda path:path.name=='native.lock')
    monkeypatch.setattr('ai_exp_app.platform_runtime.service_status',lambda config:(_ for _ in ()).throw(RuntimeError('other workspace')))
    monkeypatch.setattr('ai_exp_app.platform_runtime.stop_service',lambda config:pytest.fail('must not stop another workspace'))
    with pytest.raises(RuntimeError,match='other workspace'):native.prepare_installation(config)
    assert (tmp_path/'preserve').read_text()=='application/data'
