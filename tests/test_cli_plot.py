import json
import struct
from fastapi.testclient import TestClient
from ai_exp_app.app import create_app


def test_offline_png_export_has_expected_size_and_missing_metric_warning(tmp_path, monkeypatch):
    app = create_app(tmp_path / 'workspace')
    first, second = tmp_path / 'a', tmp_path / 'b'
    for folder in (first, second):
        folder.mkdir()
        (folder / 'args.json').write_text('{}')
    (first / 'metrics.jsonl').write_text(json.dumps({'step': 1, 'loss': 3})+'\n'+json.dumps({'step': 2, 'loss': 2})+'\n')
    (second / 'metrics.jsonl').write_text(json.dumps({'step': 1, 'accuracy': .7})+'\n')
    import ai_exp_app.analysis.api as api
    monkeypatch.setattr(api, 'remote', lambda *args: (_ for _ in ()).throw(AssertionError('PNG export must use cache')))
    client = TestClient(app)
    client.get('/')
    client.headers['origin'] = 'http://testserver'
    ids = [client.post('/api/history/import', json={'path': str(folder)}).json()['id'] for folder in (first, second)]
    response = client.post('/api/analysis/plot/png', json={'history_ids': ids, 'metric': 'loss', 'x_axis': 'step', 'settings': {'width': 640, 'height': 440, 'pixelRatio': 1}})
    assert response.status_code == 200, response.text[:200] if response.status_code != 200 else ''
    assert response.headers['content-type'] == 'image/png'
    assert response.content[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', response.content[16:24]) == (640, 440)
    assert 'loss' in response.headers['x-experiment-warnings']
    missing = client.post('/api/analysis/plot/png', json={'history_ids': ids, 'metric': 'missing', 'x_axis': 'step'})
    assert missing.status_code == 422
    oversized = client.post('/api/analysis/plot/png', json={'history_ids': ids, 'metric': 'loss', 'x_axis': 'step', 'settings': {'width': 100000}})
    assert oversized.status_code == 422


def test_plot_styles_preserve_progress_breaks_names_colors_and_log_defaults():
    from ai_exp_app.analysis.plot import create_figure
    data = {'series': [{'id':'a','name':'A','points':[{'x':1e9,'y':40},{'x':2e9,'y':None},{'x':2e9,'y':30}]},
                       {'id':'b','name':'B','points':[{'x':1e9,'y':35}]}]}
    fig = create_figure(data, {'metric':'val_ppl','x_axis':'tokens','appearance':{'b':{'name':'Baseline','order':-1,'color':'#000000'}}})
    ax = fig.axes[0]
    assert ax.get_yscale() == 'log'
    assert ax.lines[0].get_label() == 'Baseline'
    assert ax.lines[0].get_color() == '#000000'
    assert list(ax.lines[1].get_xdata()) == [1,2,2]
    assert ax.lines[1].get_ydata()[1] != ax.lines[1].get_ydata()[1]
    assert len(set(line.get_color() for line in ax.lines)) == 2
