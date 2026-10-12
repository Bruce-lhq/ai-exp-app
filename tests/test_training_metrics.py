import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ai_exp_app.db import Store
from ai_exp_app.analysis.metrics import read_metrics
from ai_exp_app.history.api import create_router
from ai_exp_app.history.importer import import_history
from ai_exp_remote.files import metric_series


def test_ca_aliases_match_local_and_remote_and_do_not_invent_missing_values(tmp_path):
    row = {'event': 'train', 'tokens_seen': 50_000_000, 'perplexity': 42,
           'ca/L01/T01/Rmin': .2, 'ca/L02/T01/Rmin': .4,
           'ca/L01/T01/Rmean': .7, 'ca/L02/T01/Rmean': .9,
           'ca/L01/T01/update_rms': .01, 'ca/L02/T01/update_rms': .03}
    path = tmp_path / 'metrics.jsonl'
    path.write_text(json.dumps(row) + '\n')
    local = read_metrics(path)
    for metric, expected in [('train_ppl', 42), ('R_min', .3), ('R_mean', .8), ('update_rms', .02)]:
        values = [r['value'] for r in local['records'] if r['metric'] == metric]
        assert abs(values[0] - expected) < 1e-12
        result = metric_series({'runs': [{'id': 'ca', 'path': str(tmp_path)}], 'metric': metric})
        assert result['ca']['points'][0]['y'] == values[0]
    path.write_text(json.dumps({'event': 'train', 'tokens_seen': 50_000_000, 'perplexity': 43}) + '\n')
    assert 'R_min' not in read_metrics(path)['metadata']
    assert metric_series({'runs': [{'id': 'base', 'path': str(tmp_path)}], 'metric': 'R_min'})['base']['points'] == []


def test_missing_ca_metric_skips_baseline_and_switching_metric_restores_it(tmp_path):
    store = Store(tmp_path / 'db')
    cache = tmp_path / 'cache'
    ids = []
    for name, ca in [('baseline', {}), ('ca', {'ca/L01/T01/Rmin': .2})]:
        folder = tmp_path / name; folder.mkdir()
        (folder / 'args.json').write_text(json.dumps({'ca_lambda': 0 if not ca else .5}))
        (folder / 'metrics.jsonl').write_text(json.dumps({'event': 'train', 'tokens_seen': 1e9, 'perplexity': 42, **ca}) + '\n')
        ids.append(import_history(store, {'kind': 'local', 'path': str(folder)}, cache, name=name)['id'])
    app = FastAPI(); app.include_router(create_router(store, cache)); client = TestClient(app)
    response = client.post('/api/analysis/series', json={'history_ids': ids, 'metric': 'R_min'}).json()
    assert [s['id'] for s in response['series']] == [ids[1]]
    assert any('baseline' in message and 'R_min' in message for message in response['warnings'])
    response = client.post('/api/analysis/series', json={'history_ids': ids, 'metric': 'train_ppl'}).json()
    assert [s['id'] for s in response['series']] == ids
    table = client.post('/api/analysis/table', json={'history_ids': ids, 'columns': [
        {'id': 'r', 'kind': 'metric', 'field': 'R_min', 'aggregate': 'min', 'title': 'R_min'}]}).json()
    assert table['rows'] == [['—'], ['0.20 @1.00B']]


def test_plot_metric_options_require_tokens_and_exclude_coordinates_and_summary(tmp_path):
    folder = tmp_path / 'run'
    folder.mkdir()
    (folder / 'args.json').write_text('{}')
    rows = [
        {'event': 'train', 'tokens_seen': 1e6, 'step': 10, 'rank': 0,
         'parameter_count': 100, 'constant_setting': .5, 'perplexity': 42, 'learning_rate': .001},
        {'event': 'train', 'tokens_seen': 2e6, 'constant_setting': .5, 'perplexity': 40, 'learning_rate': .002},
        {'event': 'final_ca_stats', 'tokens_seen': 2e6, 'summary_only': .7},
        {'event': 'train', 'step': 20, 'step_only': .8},
    ]
    (folder / 'metrics.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    store = Store(tmp_path / 'db')
    history = import_history(store, {'kind': 'local', 'path': str(folder)}, tmp_path / 'cache')
    app = FastAPI()
    app.include_router(create_router(store, tmp_path / 'cache'))
    client = TestClient(app)
    for axis in ['tokens', 'step']:
        local = client.post('/api/analysis/series', json={
            'history_ids': [history['id']], 'metric': 'train_ppl', 'x_axis': axis}).json()
        remote = metric_series({'runs': [{'id': 'run', 'path': str(folder)}],
                                'metric': 'train_ppl', 'axis': axis})['run']
        assert local['metrics'] == remote['metrics'] == ['learning_rate', 'train_ppl']
    # Summary metrics remain available for tables; only curve options are filtered.
    assert 'summary_only' in read_metrics(folder / 'metrics.jsonl')['metadata']
