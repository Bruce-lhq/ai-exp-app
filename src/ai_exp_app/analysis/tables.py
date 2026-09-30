import html
import json
import math
from .statistics import aggregate, parameter_delta
from .templates import normalize_columns
from ai_exp_app.parameters.validation import parse_number


def format_value(value, style=None, signed=False):
    if value is None:
        return '—'
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value) if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)
    if not math.isfinite(value):
        return '—'
    style = style if isinstance(style, dict) else {'type': style or 'fixed'}
    digits = max(0, min(12, int(style.get('digits', style.get('decimals', 2)))))
    kind = style.get('type', style.get('mode', 'fixed'))
    sign = '+' if signed else ''
    if 0 < abs(value) < 0.01 or kind == 'scientific':
        places = digits if kind == 'fixed' else max(0, digits - 1)
        result = format(value, f'{sign}.{places}e')
        mantissa, exponent = result.split('e')
        return mantissa.rstrip('0').rstrip('.') + 'e' + str(int(exponent))
    units = [('', 1), ('K', 1e3), ('M', 1e6), ('B', 1e9), ('T', 1e12)]
    unit = max(i for i, (_, factor) in enumerate(units) if abs(value) >= factor) if abs(value) >= 1 else 0
    spec = f'{sign}.{digits}f' if kind == 'fixed' else f'{sign}.{max(digits, 1)}g'
    result = format(value / units[unit][1], spec)
    if abs(float(result)) >= 1000 and unit < len(units) - 1:
        unit += 1
        result = format(value / units[unit][1], spec)
    if 'e' in result:
        result = format(float(result), f'{sign}f').rstrip('0').rstrip('.')
    return result + units[unit][0]


def metric_value(run, column):
    return aggregate([r['value'] for r in run.get('records', []) if r['metric'] == column['field']], column['aggregate'])


def format_speed(value, style=None, signed=False):
    if value is None:
        return '—'
    return format_value(value, style, signed) + ' tok/s'


def token_position(tokens):
    value = tokens / 1e9
    # Keep trailing zeroes: 6B -> 6.00B, 0.2B -> 0.200B.
    rounded = float(format(value, '.3g'))
    decimals = max(0, 2 - math.floor(math.log10(abs(rounded)))) if rounded else 2
    return format(rounded, f'.{decimals}f') + 'B'


def metric_position(run, column, value):
    return min((r['tokens'] for r in run.get('records', [])
                if r['metric'] == column['field'] and r['value'] == value
                and isinstance(r.get('tokens'), (int, float))
                and not isinstance(r['tokens'], bool) and math.isfinite(r['tokens'])), default=None)


def escape_cell(value):
    return html.escape(str(value), quote=False).replace('\\', '\\\\').replace('|', '\\|').replace('\n', '<br>')


def render_table(runs, columns, baseline=None):
    columns = normalize_columns(columns)
    by_id = {c['id']: c for c in columns}
    rows, warnings = [], []
    for run in runs:
        row = []
        for c in columns:
            kind, signed, suffix = c['kind'], False, ''
            speed = kind == 'metric' and c['field'] == 'tokens_per_second'
            if kind == 'name':
                value = run.get('name', run.get('display_name', run['id']))
            elif kind == 'notes':
                value = run.get('notes', '')
            elif kind == 'parameter':
                params = run.get('parameters', {})
                value = params.get(c['field'], params.get('training', {}).get(c['field'], params.get('runtime', {}).get(c['field'])))
                if isinstance(value, str):
                    try:
                        value = parse_number(value)
                    except ValueError:
                        pass
            elif kind == 'metric':
                value = metric_value(run, c)
                if c['aggregate'] in {'min', 'max'} and value is not None:
                    tokens = metric_position(run, c, value)
                    if tokens is not None:
                        suffix = ' @' + token_position(tokens)
                    else:
                        warnings.append(f"{run.get('name', run['id'])}：{c['title']} 缺少极值对应的 token 位置")
                elif c['aggregate'] == 'final' and value is not None:
                    records = [r for r in run.get('records', []) if r['metric'] == c['field']
                               and isinstance(r.get('value'), (int, float)) and math.isfinite(r['value'])]
                    tokens = records[-1].get('tokens') if records else None
                    if isinstance(tokens, (int, float)) and math.isfinite(tokens):
                        suffix = ' @' + token_position(tokens)
                    else:
                        warnings.append(f"{run.get('name', run['id'])}：{c['title']} 缺少末值对应的 token 位置")
            elif kind in {'metric_delta', 'parameter_delta'}:
                if baseline and run['id'] == baseline['id']:
                    row.append('-')
                    continue
                signed = True
                if kind == 'metric_delta':
                    parent = by_id[c['parent_id']]
                    speed = parent['field'] == 'tokens_per_second'
                    a, b = metric_value(run, parent), metric_value(baseline or {}, parent)
                    value = a - b if a is not None and b is not None else None
                else:
                    value = parameter_delta(run.get('parameter_count'), (baseline or {}).get('parameter_count'))
                    suffix = '%' if value is not None else ''
            else:
                value = run.get('parameter_count')
            if value is None:
                warnings.append(f"{run.get('name', run['id'])}：{c['title']} 缺少数据")
            formatter = format_speed if speed else format_value
            row.append(formatter(value, c.get('format'), signed) + suffix)
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
    return {'headers': headers, 'rows': rows, 'markdown': markdown, 'warnings': list(dict.fromkeys(warnings))}
