#!/usr/bin/env python3
"""Convert a CSV or JSONL file into a separate canonical numeric metrics JSONL."""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import tempfile


def normalize(source, destination, mapping, overwrite=False):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('The output must be separate from the original metrics')
    if destination.exists() and not overwrite:
        raise ValueError('Output exists; select a new file or explicitly use --overwrite')
    if not isinstance(mapping, dict) or not mapping or any(not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()):
        raise ValueError('Mapping must be an object of output-field: source-field strings')
    destination.parent.mkdir(parents=True, exist_ok=True)
    written, skipped, missing = 0, 0, set()
    temporary = None
    try:
        with source.open(encoding='utf-8', newline='') as stream, tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            rows = csv.DictReader(stream) if source.suffix.lower() == '.csv' else (json.loads(line) for line in stream if line.strip())
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('Every metrics record must be an object')
                converted = {}
                for target, field in mapping.items():
                    value = row.get(field)
                    if field not in row:
                        value = row
                        for part in field.split('.'):
                            value = value.get(part) if isinstance(value, dict) else None
                    if value is None or value == '':
                        missing.add(field)
                        continue
                    if isinstance(value, bool):
                        missing.add(field)
                        continue
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        missing.add(field)
                        continue
                    if not math.isfinite(numeric):
                        missing.add(field)
                        continue
                    converted[target] = int(numeric) if numeric.is_integer() else numeric
                if converted:
                    output.write(json.dumps(converted, allow_nan=False) + '\n')
                    written += 1
                else:
                    skipped += 1
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'written_records': written, 'skipped_records': skipped, 'missing_or_invalid_fields': sorted(missing), 'output': str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True, help='JSON object: canonical field to source field; dotted nested keys supported')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        result = normalize(args.input, args.output, json.loads(args.map.read_text(encoding='utf-8')), args.overwrite)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
