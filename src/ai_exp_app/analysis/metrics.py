import json
import math
from .trajectory import effective_trajectory

AXES = {'tokens', 'tokens_seen', 'total_tokens', 'global_tokens', 'step', 'global_step', 'elapsed_s', 'elapsed_seconds', 'time', 'timestamp', 'rank', 'epoch', 'optimizer_step', 'data_step'}


def ca_window_metrics(values):
    """Match plot_metric.py: mean of the per-layer/per-call window statistics."""
    result = {}
    for name, suffixes in {'R_min': ('Rmin', 'R_min'), 'R_mean': ('Rmean', 'R_mean'),
                           'update_rms': ('update_rms',)}.items():
        if name in values:
            continue
        direct = next((values[key] for key in suffixes if key in values), None)
        samples = [value for key, value in values.items()
                   if key.startswith('ca/') and key.rsplit('/', 1)[-1] in suffixes
                   and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)]
        if isinstance(direct, (int, float)) and not isinstance(direct, bool) and math.isfinite(direct):
            result[name] = direct
        elif samples:
            result[name] = sum(samples) / len(samples)
    return result


def read_metrics(path, run_id='', attempts=None):
    records, warnings, metadata = [], [], {}
    parameter_count = None
    if not path.exists():
        return {'records': [], 'warnings': ['缺少 metrics.jsonl'], 'metadata': {}, 'parameter_count': None}
    current_attempt = None
    boundaries = {a['source_index']: a['id'] for a in attempts or [] if isinstance(a.get('source_index'), int)}
    with path.open(errors='replace') as stream:
        for index, line in enumerate(stream):
            if index in boundaries:
                current_attempt = boundaries[index]
            try:
                item = json.loads(line)
            except ValueError:
                warnings.append(f'第 {index + 1} 行指标不完整或损坏，已跳过')
                continue
            if not isinstance(item, dict):
                continue
            event = str(item.get('event', item.get('type', ''))).lower()
            current_attempt = item.get('attempt_id', current_attempt)
            for key in ('parameter_count', 'num_parameters', 'num_params', 'total_params', 'n_params', 'total_parameters', 'trainable_parameters'):
                if isinstance(item.get(key), (int, float)):
                    count = item.get('total_parameters', item[key])
                    if math.isfinite(count) and count >= 0:
                        parameter_count = count
            values = dict(item)
            if isinstance(item.get('metrics'), dict):
                values.update(item['metrics'])
            if event in {'train', 'training'}:
                values.update(ca_window_metrics(values))
            for key, value in values.items():
                if key in AXES or key in {'parameter_count', 'num_parameters', 'num_params', 'total_params', 'n_params', 'total_parameters', 'trainable_parameters'} or isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if not math.isfinite(value):
                    warnings.append(f'第 {index + 1} 行 {key} 不是有限数，已跳过')
                    continue
                metric = key
                if key in {'perplexity', 'ppl', 'loss'}:
                    prefix = 'val' if event in {'validation', 'val', 'eval', 'evaluation'} else 'train' if event in {'train', 'training'} else None
                    if prefix:
                        metric = prefix + '_' + ('ppl' if key in {'perplexity', 'ppl'} else key)
                tokens = next((item[k] for k in ('tokens_seen', 'total_tokens', 'global_tokens', 'tokens') if isinstance(item.get(k), (int, float))), None)
                step = item.get('step', item.get('global_step', item.get('optimizer_step')))
                elapsed = item.get('elapsed_s', item.get('elapsed_seconds'))
                tokens = tokens if isinstance(tokens, (int, float)) and math.isfinite(tokens) else None
                step = step if isinstance(step, (int, float)) and math.isfinite(step) else None
                elapsed = elapsed if isinstance(elapsed, (int, float)) and math.isfinite(elapsed) else None
                records.append({'run_id': run_id, 'attempt_id': current_attempt, 'source_index': index,
                    'metric': metric, 'value': value, 'tokens': tokens, 'step': step, 'elapsed_s': elapsed, 'event': event})
                metadata[metric] = {'name': metric, 'unit': None, 'event': event}
    if len(attempts or []) > 1:
        for record in records:
            record['elapsed_s'] = None
        warnings.append('续跑实验缺少可靠的累计有效耗时映射，耗时轴不可用')
    return {'records': effective_trajectory(records, attempts or []), 'warnings': warnings,
            'metadata': metadata, 'parameter_count': parameter_count}
