import json
from ai_exp_app.analysis.metrics import read_metrics
from ai_exp_app.analysis.trajectory import effective_trajectory
from ai_exp_app.analysis.tables import render_table
from ai_exp_app.analysis.templates import normalize_columns, ensure_default
from ai_exp_app.db import Store


def test_real_validation_tokens_and_metrics(tmp_path):
    file = tmp_path / 'metrics.jsonl'
    file.write_text('\n'.join([json.dumps({'event':'start','total_parameters':120000000,'trainable_parameters':119000000}),
        json.dumps({'event':'train','tokens_seen':100,'perplexity':50,'optimizer_step':2}),
        json.dumps({'event':'validation','tokens_seen':100,'tokens':999,'perplexity':42}),
        '{broken', json.dumps({'event':'validation','tokens_seen':200,'perplexity':float('nan')})]))
    result = read_metrics(file)
    val = [r for r in result['records'] if r['metric'] == 'val_ppl']
    assert len(val) == 1 and val[0]['tokens'] == 100
    assert result['parameter_count'] == 120000000
    assert len(result['warnings']) == 2


def test_resume_tail_and_metric_boundaries():
    records = [{'attempt_id':'a','tokens':100,'metric':'val_ppl','value':80},
               {'attempt_id':'a','tokens':200,'metric':'val_ppl','value':70},
               {'attempt_id':'b','tokens':200,'metric':'val_ppl','value':69}]
    assert [r['value'] for r in effective_trajectory(records,[{'id':'a'},{'id':'b','resume_tokens':100}])] == [80,69]


def test_table_raw_precision_title_bindings_final_and_percent():
    columns = [{'id':'m','kind':'metric','field':'val_ppl','aggregate':'final','title':'任意标题','format':{'type':'fixed','digits':2}},
               {'id':'d','kind':'metric_delta','parent_id':'m','title':'变化','format':{'type':'fixed','digits':3}},
               {'id':'p','kind':'parameter_delta','title':'参数变化'}]
    base = {'id':'base','name':'Baseline','parameter_count':100,'records':[{'metric':'val_ppl','value':1.234}]}
    current = {'id':'x','name':'X','parameter_count':120,'records':[{'metric':'val_ppl','value':1}, {'metric':'val_ppl','value':1.235}]}
    result = render_table([base,current], columns, base)
    assert result['headers'][0] == '任意标题'
    assert result['rows'][1] == ['1.24','+0.001','+20%']
    assert result['rows'][0][1:] == ['-','-']


def test_stopped_suffix_missing_data_escaping():
    columns = [{'id':'n','kind':'name','title':'实验'}, {'id':'m','kind':'metric','field':'val_ppl','aggregate':'min','title':'最佳'}]
    record = {'id':'a','name':'A|<script>','status':'stopped','records':[{'metric':'val_ppl','tokens':1e9,'value':40}]}
    result = render_table([record],columns)
    assert result['rows'][0][1] == '40 @1B'
    assert '\\|' in result['markdown'] and '&lt;script&gt;' in result['markdown']
    assert '最后已记录进度' in result['markdown']


def test_delta_follows_parent_and_default_not_overwritten(tmp_path):
    columns = [{'id':'d','kind':'metric_delta','parent_id':'m','title':'差值'},
               {'id':'n','kind':'name','title':'实验'},
               {'id':'m','kind':'metric','field':'val_ppl','aggregate':'min','title':'最佳'}]
    assert [c['id'] for c in normalize_columns(columns)] == ['n','m','d']
    store = Store(tmp_path / 'db')
    ensure_default(store)
    record = store.get('templates','default')
    record['name'] = 'edited'
    store.put('templates','default',record)
    ensure_default(store)
    assert store.get('templates','default')['name'] == 'edited'


def test_managed_attempt_source_boundaries_replace_old_tail(tmp_path):
    file = tmp_path / 'metrics.jsonl'
    file.write_text(''.join(json.dumps({'event':'validation','tokens_seen':n,'perplexity':v})+'\n' for n,v in [(100,50),(200,40),(150,45)]))
    result = read_metrics(file, 'a', [{'id':'old','source_index':0,'resume_tokens':0}, {'id':'new','source_index':2,'resume_tokens':100}])
    assert [r['value'] for r in result['records']] == [50,45]
    assert [r['attempt_id'] for r in result['records']] == ['old','new']
