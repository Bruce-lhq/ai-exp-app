import math


def aggregate(values, method):
    valid = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    if method not in {'min', 'max', 'final'}:
        raise ValueError('未知统计方式')
    if not valid:
        return None
    return min(valid) if method == 'min' else max(valid) if method == 'max' else valid[-1]


def parameter_delta(current, baseline):
    if current is None or baseline is None or baseline <= 0:
        return None
    return (current / baseline - 1) * 100
