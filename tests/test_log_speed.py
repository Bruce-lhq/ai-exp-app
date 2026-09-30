from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_exp_app.analysis import api
from ai_exp_app.analysis.logs import read_log_metrics
from ai_exp_app.analysis.tables import render_table
from ai_exp_app.db import Store


def test_log_speed_units_and_missing_progress(tmp_path):
    path = tmp_path / 'train.log'
    path.write_text('\n'.join([
        '0.01B/10B val_ppl=NA (67k tok/s, 2m)',
        '0.02b/10b (0.12M TOK/S, 3m)',
        '30M/10B (125000 tok/s, 4m)',
        'unknown progress (126K tok/s, 5m)',
        '0.05B/10B (-1k tok/s, 6m)',
        '0.06B/10B (1e999k tok/s, 7m)',
        '0.07B/10B (nank tok/s, 8m)',
        'summary: 900k tok/s',
    ]))
    result = read_log_metrics(path)
    assert [r['value'] for r in result['records']] == [67000, 120000, 125000, 126000]
    assert [r['tokens'] for r in result['records']] == [1e7, 2e7, 3e7, None]
    assert result['metadata']['tokens_per_second']['unit'] == 'tok/s'
    assert not read_log_metrics(tmp_path / 'missing')['records']


def test_speed_table_auto_units_extrema_and_delta():
    columns = [{'id':method, 'kind':'metric', 'field':'tokens_per_second', 'aggregate':method, 'title':method}
               for method in ['min', 'max', 'final']]
    columns.append({'id':'delta', 'kind':'metric_delta', 'parent_id':'final', 'title':'delta'})
    run = {'id':'a', 'records':[
        {'metric':'tokens_per_second', 'value':67000, 'tokens':1e7},
        {'metric':'tokens_per_second', 'value':1250000, 'tokens':2e7},
        {'metric':'tokens_per_second', 'value':120000, 'tokens':3e7}]}
    baseline = {'id':'b', 'records':[{'metric':'tokens_per_second', 'value':100000, 'tokens':3e7}]}
    assert render_table([run], columns, baseline)['rows'][0] == [
        '67.00K tok/s @0.0100B', '1.25M tok/s @0.0200B', '120.00K tok/s @0.0300B', '+20.00K tok/s']


def test_log_cache_refresh_does_not_reparse_metrics_or_mutate_cache(tmp_path, monkeypatch):
    store = Store(tmp_path / 'db')
    store.put('history', 'run', {'id':'run', 'name':'run', 'cache_dir':str(tmp_path)})
    (tmp_path / 'metrics.jsonl').write_text('{"event":"validation","tokens_seen":10000000,"perplexity":42}\n')
    log = tmp_path / 'train.log'
    log.write_text('0.01B/10B (67k tok/s, 2m)\n')
    calls = {'metrics':0, 'log':0}
    original_metrics, original_logs = api.read_metrics, api.read_log_metrics
    def metrics(*args):
        calls['metrics'] += 1
        return original_metrics(*args)
    def logs(*args):
        calls['log'] += 1
        return original_logs(*args)
    monkeypatch.setattr(api, 'read_metrics', metrics)
    monkeypatch.setattr(api, 'read_log_metrics', logs)
    app = FastAPI()
    app.include_router(api.create_router(store))
    client = TestClient(app)
    url = '/api/history/run/metrics'
    assert len(client.get(url).json()['records']) == 2
    assert len(client.get(url).json()['records']) == 2
    assert calls == {'metrics':1, 'log':1}
    log.write_text(log.read_text() + '0.02B/10B (120k tok/s, 3m)\n')
    assert len(client.get(url).json()['records']) == 3
    assert calls == {'metrics':1, 'log':2}
    log.unlink()
    assert len(client.get(url).json()['records']) == 1
    assert calls == {'metrics':1, 'log':3}
