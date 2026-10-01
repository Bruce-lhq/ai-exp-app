"""Record release hashes and distinguish automation from human acceptance."""
import hashlib
import json
from pathlib import Path
import platform

root = Path(__file__).resolve().parents[1] / 'dist'
artifacts = root / 'releases'
paths = sorted(path for path in artifacts.iterdir() if path.is_file() and path.name != 'SHA256SUMS.txt')
if not paths:
    raise SystemExit('No release packages were generated')
(artifacts / 'SHA256SUMS.txt').write_text(''.join(
    hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in paths), encoding='utf-8')
verification = root / 'verification'
verification.mkdir(parents=True, exist_ok=True)
(verification / 'acceptance.json').write_text(json.dumps({
    'platform': platform.platform(), 'architecture': platform.machine(),
    'automated_reports': sorted(path.name for path in verification.glob('*-*.json')),
    'human_acceptance': False,
    'windows_note': 'Windows Server CI is not Windows 11 human acceptance.' if platform.system() == 'Windows' else None,
}, indent=2), encoding='utf-8')
