import html
import json
from .statistics import aggregate, parameter_delta
from .templates import normalize_columns


def format_value(value, style=None, signed=False):
    if value is None:
        return '—'
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value) if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)
    style = style if isinstance(style, dict) else {'type': style or 'compact'}
    digits = max(0, min(12, int(style.get('digits', style.get('decimals', 4)))))
    kind = style.get('type', style.get('mode', 'compact'))
    sign = '+' if signed else ''
    if kind == 'fixed':
        return format(value, f'{sign}.{digits}f')
    if kind == 'scientific':
        return format(value, f'{sign}.{digits}e')
    for suffix, factor in [('B', 1e9), ('M', 1e6), ('K', 1e3)]:
        if abs(value) >= factor:
            return format(value / factor, f'{sign}.{digits}g') + suffix
    return format(value, f'{sign}.{max(digits, 1)}g')


def metric_value(run, column):
    return aggregate([r['value'] for r in run.get('records', []) if r['metric'] == column['field']], column['aggregate'])


def escape_cell(value):
    return html.escape(str(value), quote=False).replace('\\', '\\\\').replace('|', '\\|').replace('\n', '<br>')


def render_table(runs, columns, baseline=None):
    columns = normalize_columns(columns)
    by_id = {c['id']: c for c in columns}
    rows, warnings, footnotes = [], [], []
    for run in runs:
        row = []
        stopped = run.get('status') == 'stopped'
        stop_tokens = run.get('stop_tokens')
        if stopped and stop_tokens is None:
            stop_tokens = max((r['tokens'] for r in run.get('records', []) if r.get('tokens') is not None), default=None)
            footnotes.append(f"{run.get('name', run['id'])}：停止进度未知，@ 标注为最后已记录进度。")
        for c in columns:
            kind, signed, suffix = c['kind'], False, ''
            if kind == 'name':
                value = run.get('name', run.get('display_name', run['id']))
            elif kind == 'notes':
                value = run.get('notes', '')
            elif kind == 'parameter':
                params = run.get('parameters', {})
                value = params.get(c['field'], params.get('training', {}).get(c['field'], params.get('runtime', {}).get(c['field'])))
            elif kind == 'metric':
                value = metric_value(run, c)
                if stopped and stop_tokens is not None and value is not None:
                    suffix = f' @{stop_tokens / 1e9:g}B'
            elif kind in {'metric_delta', 'parameter_delta'}:
                if baseline and run['id'] == baseline['id']:
                    row.append('-')
                    continue
                signed = True
                if kind == 'metric_delta':
                    parent = by_id[c['parent_id']]
                    a, b = metric_value(run, parent), metric_value(baseline or {}, parent)
                    value = a - b if a is not None and b is not None else None
                else:
                    value = parameter_delta(run.get('parameter_count'), (baseline or {}).get('parameter_count'))
                    suffix = '%' if value is not None else ''
            else:
                value = run.get('parameter_count')
            if value is None:
                warnings.append(f"{run.get('name', run['id'])}：{c['title']} 缺少数据")
            row.append(format_value(value, c.get('format'), signed) + suffix)
        rows.append(row)
    if baseline:
        base_progress = max((r['tokens'] for r in baseline.get('records', []) if r.get('tokens') is not None), default=None)
        for run in runs:
            progress = max((r['tokens'] for r in run.get('records', []) if r.get('tokens') is not None), default=None)
            if progress is not None and base_progress is not None and progress != base_progress:
                warnings.append(f"{run.get('name', run['id'])} 与 baseline 的训练进度不同")
    headers = [c['title'] for c in columns]
    markdown = '\n'.join(['| ' + ' | '.join(map(escape_cell, headers)) + ' |',
                          '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                         ['| ' + ' | '.join(map(escape_cell, row)) + ' |' for row in rows])
    if footnotes:
        markdown += '\n\n' + '\n'.join(escape_cell(n) for n in dict.fromkeys(footnotes))
    return {'headers': headers, 'rows': rows, 'markdown': markdown, 'warnings': list(dict.fromkeys(warnings))}
