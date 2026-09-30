import json
from ai_exp_remote import files


def test_run_progress_mirrors_dashboard(tmp_path):
    (tmp_path/'args.json').write_text(json.dumps({'max_tokens': 2000000000, 'warmup_tokens': 20000000}))
    (tmp_path/'metrics.jsonl').write_text('\n'.join(
        json.dumps({'tokens_seen': i*100_000_000, 'elapsed_s': i*1000.0, 'event': 'train'})
        for i in range(1, 5)) + '\n')
    result = files.run_progress(dict(remote_path=str(tmp_path), status='running'))
    assert result['progress'] == '0.40B/2B'
    # 300M tokens over 3000s after the warmup anchor → 16000s left → 4h27m.
    assert result['remaining'] == '4h27m'

def test_run_progress_omits_remaining_without_anchor_or_when_idle(tmp_path):
    (tmp_path/'args.json').write_text(json.dumps({'max_tokens': 2000000000}))
    (tmp_path/'metrics.jsonl').write_text(json.dumps({'tokens_seen': 100_000_000, 'elapsed_s': 500.0, 'event': 'train'}) + '\n')
    assert 'remaining' not in files.run_progress(dict(remote_path=str(tmp_path), status='running'))
    (tmp_path/'metrics.jsonl').write_text('')
    assert files.run_progress(dict(remote_path=str(tmp_path), status='paused')) == {}


def test_small_run_progress_does_not_round_to_zero(tmp_path):
    (tmp_path/'args.json').write_text(json.dumps({'max_tokens': 1000000}))
    (tmp_path/'metrics.jsonl').write_text(json.dumps({'tokens_seen': 245872, 'elapsed_s': 20}) + '\n')
    result = files.run_progress(dict(remote_path=str(tmp_path), status='paused'))
    assert result['progress'] == '245.87K/1M'
