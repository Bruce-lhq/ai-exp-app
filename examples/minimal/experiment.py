"""A CPU-only output-protocol example, not a model training benchmark."""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--steps', type=int, default=8)
    parser.add_argument('--rate', type=float, default=0.1)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    value = 2.0
    with (output / 'metrics.jsonl').open('w') as stream:
        for step in range(1, args.steps + 1):
            value -= args.rate * value
            item = {'step': step, 'elapsed_s': time.monotonic() - started,
                    'metrics': {'loss': value * value, 'accuracy': 1 / (1 + value * value)}}
            stream.write(json.dumps(item, allow_nan=False) + '\n')
            stream.flush()
            print(f'step={step} loss={item["metrics"]["loss"]:.4f}', flush=True)
            time.sleep(0.05)
    print('Finished.', flush=True)


if __name__ == '__main__':
    main()
