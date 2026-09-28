import uuid


def normalize_columns(columns):
    normalized, seen = [], set()
    for raw in columns:
        c = dict(raw)
        c['id'] = c.get('id') or str(uuid.uuid4())
        if c['id'] in seen:
            raise ValueError('列 ID 重复')
        seen.add(c['id'])
        c['kind'] = {'delta': 'metric_delta', 'parameter_count_delta': 'parameter_delta'}.get(c['kind'], c['kind'])
        c['field'] = c.get('field', c.get('key'))
        c['aggregate'] = c.get('aggregate', c.get('stat', 'final'))
        c['title'] = c.get('title', c.get('header', c['field'] or c['kind']))
        if c['kind'] not in {'name', 'parameter', 'metric', 'metric_delta', 'parameter_count', 'parameter_delta', 'notes'}:
            raise ValueError('未知列类型')
        if c['aggregate'] not in {'min', 'max', 'final'}:
            raise ValueError('未知统计方式')
        normalized.append(c)
    by_id = {c['id']: c for c in normalized}
    for c in normalized:
        if c['kind'] == 'metric_delta' and by_id.get(c.get('parent_id'), {}).get('kind') != 'metric':
            raise ValueError('差值列必须引用指标列')
    result = []
    for c in normalized:
        if c['kind'] == 'metric_delta':
            continue
        result.append(c)
        result.extend(d for d in normalized if d['kind'] == 'metric_delta' and d.get('parent_id') == c['id'])
    return result


def ensure_default(store):
    if store.get('templates', 'default'):
        return
    columns = [{'id': 'name', 'kind': 'name', 'title': '实验'}]
    for stat, title in [('min', 'val_ppl best(min)'), ('final', 'val_ppl final')]:
        columns.extend([{'id': stat, 'kind': 'metric', 'field': 'val_ppl', 'aggregate': stat, 'title': title},
                        {'id': stat + '_delta', 'kind': 'metric_delta', 'parent_id': stat, 'title': '△ vs baseline'}])
    columns.extend([{'id': 'params', 'kind': 'parameter_count', 'title': '参数量'},
                    {'id': 'params_delta', 'kind': 'parameter_delta', 'title': '相对 baseline 参数量'}])
    store.put('templates', 'default', {'id': 'default', 'name': '默认模板', 'columns': normalize_columns(columns)})
