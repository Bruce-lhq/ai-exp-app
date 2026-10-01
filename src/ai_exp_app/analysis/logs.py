import math
import re


NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?'
SPEED = re.compile(r'\(\s*(' + NUMBER + r')\s*([kmb]?)\s*tok/s\s*[,)]', re.IGNORECASE)
PROGRESS = re.compile(r'(?<![\w.])(' + NUMBER + r')\s*([kmb])\s*/\s*' + NUMBER + r'\s*[kmb]', re.IGNORECASE)
FACTORS = {'': 1, 'k': 1e3, 'm': 1e6, 'b': 1e9}


def read_log_metrics(path, run_id=''):
    records = []
    if path.exists():
        with path.open(encoding='utf-8', errors='replace') as stream:
            for index, line in enumerate(stream):
                speed = SPEED.search(line)
                if not speed:
                    continue
                value = float(speed[1]) * FACTORS[speed[2].lower()]
                if not math.isfinite(value) or value < 0:
                    continue
                progress = PROGRESS.search(line[:speed.start()])
                tokens = float(progress[1]) * FACTORS[progress[2].lower()] if progress else None
                if tokens is not None and (not math.isfinite(tokens) or tokens < 0):
                    tokens = None
                records.append({'run_id': run_id, 'source_index': index, 'metric': 'tokens_per_second',
                                'value': value, 'tokens': tokens, 'step': None, 'elapsed_s': None, 'event': 'train'})
    metadata = {'tokens_per_second': {'name': 'tokens_per_second', 'unit': 'tok/s', 'event': 'train'}} if records else {}
    return {'records': records, 'metadata': metadata}
